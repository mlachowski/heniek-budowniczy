import dataclasses
import enum
import json
import os
import sys
import time
import traceback
from copy import copy
from typing import Optional
from datetime import datetime

import click
import click_config_file
from termcolor import cprint
from utils import init_and_log_in, do_click, get_path, get_config, normalize, printProgressBar
from selenium.webdriver.common.by import By


BUILDING_BASE_URL = "https://www.operatorratunkowy.pl/buildings/"
VEHICLE_BASE_URL = "https://www.operatorratunkowy.pl/vehicles/"


class BuildingCategory(enum.Enum):
    firehouse = 0


@dataclasses.dataclass
class Building:
    id: str
    name: str
    cpr: str
    category: BuildingCategory
    level: int
    crew: int
    free_space: Optional[int]
    vehicles_number: Optional[int]
    vehicles: list
    crew_members: list
    available_crew: Optional[int]

    def __str__(self):
        return f"{self.name} ({self.id})"


@dataclasses.dataclass
class CrewMember:
    name: str
    education: frozenset
    assigned: str
    state: str
    available: bool


@dataclasses.dataclass
class Vehicle:
    name: str
    id: str

    def __str__(self):
        return f"{self.name} ({self.id})"


@dataclasses.dataclass
class VehicleTarget:
    count: int
    crew: int
    education: Optional[list]

    @property
    def education_f(self):
        return frozenset(self.education or [''])


def get_list_of_buildings(driver, cpr):
    driver.get(f"{BUILDING_BASE_URL}{cpr}")
    do_click(driver, driver.find_element(By.XPATH, '//*[@id="tabs"]/li[4]/a'))
    time.sleep(2)
    buildings = list(_get_table_rows(driver, "building_table"))

    parsed_buildings = list()
    l = len(buildings)
    printProgressBar(0, l, prefix="Parsing buildings data:", suffix="Complete", length=50)
    for i, building in enumerate(buildings):
        building_type, name, level, _, crew, _, _ = list(building.find_elements(By.TAG_NAME, "td"))
        building_type = building_type.find_element(By.TAG_NAME, "img").get_attribute("alt")
        if building_type == "Building_fire":
            building_id = (
                name.find_element(By.TAG_NAME, "a").get_attribute("href").split("/")[-1:][0]
            )
            parsed_buildings.append(
                Building(
                    building_id,
                    name.text.strip(),
                    cpr,
                    BuildingCategory.firehouse,
                    int(normalize(level)),
                    int(normalize(crew)),
                    None,
                    None,
                    list(),
                    list(),
                    None,
                )
            )
        printProgressBar(i+1, l, prefix="Parsing buildings data:", suffix="Complete", length=50)

    return parsed_buildings


def get_building_details(driver, building):
    driver.get(f"{BUILDING_BASE_URL}{building.id}")

    space_details = driver.find_element(
        By.XPATH, '//*[@id="iframe-inside-container"]/dl/dd[2]'
    ).text.split(" ")
    space_taken = int(space_details[0].strip())
    space_available = int(space_details[2].strip())
    building.free_space = space_available - space_taken
    building.vehicles_number = space_taken

    vehicles = _get_table_rows(driver, "vehicle_table")
    vehicles_parsed = list()
    for vehicle in vehicles:
        a = list(vehicle.find_elements(By.TAG_NAME, "td"))[1].find_element(By.TAG_NAME, "a")
        vehicles_parsed.append(Vehicle(normalize(a), a.get_attribute("href").split("/")[-1:][0]))
    building.vehicles = vehicles_parsed


def buy_vehicles(driver, building, to_buy):
    driver.get(f"{BUILDING_BASE_URL}{building.id}/vehicles/new")
    for car, count in to_buy.items():
        for _ in range(0, count):
            time.sleep(0.3)
            vehicle = _find_vehicle(driver, car)
            if vehicle:
                cprint(f'BUYING {car}', 'green')
                do_click(driver, vehicle)


def get_crew_members(driver, building):
    driver.get(f"{BUILDING_BASE_URL}{building.id}/personals")

    crew_members = _get_table_rows(driver, "personal_table")
    crew_members_parsed = list()
    available_crew = 0
    for crew_member in crew_members:
        name, education, assigned, state, _ = list(crew_member.find_elements(By.TAG_NAME, "td"))
        assigned_n = normalize(assigned)
        state_n = normalize(state)
        crew_member_parsed = CrewMember(
            name=name.text.strip(),
            education=frozenset(normalize(education).split(",")),
            assigned=assigned_n,
            state=state_n,
            available=state_n == "Dostepne" and assigned_n == "",
        )
        crew_members_parsed.append(crew_member_parsed)
        if crew_member_parsed.available:
            available_crew += 1

    building.crew_members = crew_members_parsed
    building.available_crew = available_crew
    return crew_members_parsed


def _get_table_rows(driver, table_id):
    table = driver.find_element(By.ID, table_id).find_element(By.TAG_NAME, "tbody")
    return table.find_elements(By.TAG_NAME, "tr")


def _find_vehicle(driver, vehicle_name):
    do_click(driver, driver.find_element(By.XPATH, '//*[@id="tabs"]/li[1]/a'))
    time.sleep(0.2)
    for vehicle in driver.find_elements(By.CLASS_NAME, "vehicle_type"):
        if normalize(vehicle.find_element(By.TAG_NAME, "h3")) == vehicle_name:
            return list(vehicle.find_elements(By.TAG_NAME, "a"))[1]
    do_click(driver, driver.find_element(By.XPATH, '//*[@id="tabs"]/li[2]/a'))
    time.sleep(0.2)
    for vehicle in driver.find_elements(By.CLASS_NAME, "vehicle_type"):
        if normalize(vehicle.find_element(By.TAG_NAME, "h3")) == vehicle_name:
            return list(vehicle.find_elements(By.TAG_NAME, "a"))[1]


def check_what_to_buy(building, to_buy):
    cars_to_buy = {k: t.count for k, t in to_buy.items()}
    current_cars = {}
    missing = copy(cars_to_buy)
    for car in building.vehicles:
        if cars_to_buy.get(car.name) is not None:
            current_cars[car.name] = current_cars.get(car.name, 0) + 1
            missing[car.name] = cars_to_buy[car.name] - current_cars[car.name]
    return {k: c for k, c in missing.items() if c > 0}


def expand_building(driver, building, space):
    for _ in range(0, space):
        driver.get(f"{BUILDING_BASE_URL}{building.id}/expand_do/credits")
        time.sleep(0.2)


def assign_crew(driver, vehicle, vehicle_target_data, dry_run):
    driver.get(f"{VEHICLE_BASE_URL}{vehicle.id}/zuweisung")
    time.sleep(0.3)
    assigned = int(driver.find_element(By.ID, "count_personal").text.strip())
    want_to_assign = vehicle_target_data.crew
    target_education = vehicle_target_data.education_f
    if assigned < want_to_assign:
        to_assign = want_to_assign - assigned
        personal_table = _get_table_rows(driver, "personal_table")
        cprint(f"Trying to assign {to_assign}, education: {target_education}. {vehicle}", 'yellow')
        for person in personal_table:
            if to_assign <= 0:
                cprint("Done", 'green')
                return

            _, education, state, assign = list(person.find_elements(By.TAG_NAME, "td"))
            education = frozenset(normalize(education).split(','))
            state = normalize(state)
            assigned = normalize(assign) != "Przydziel pojazd"
            if education == target_education and state == "Dostepne" and not assigned:
                if not dry_run:
                    do_click(driver, assign.find_element(By.TAG_NAME, "a"))
                    time.sleep(0.3)
                to_assign -= 1
        cprint(f'Cant assign all crew {vehicle}', 'red')
    else:
        print(f"No need to assign {vehicle}")


def check_is_crew_available(building, target_to_buy, to_buy):
    needed_crew = sum(
        [
            target_to_buy[car].crew * count
            for car, count in to_buy.items()
            if target_to_buy[car].education is None
        ]
    )
    if building.available_crew and building.available_crew < needed_crew:
        cprint(f"Missing crew. Available: {building.available_crew}, needed: {needed_crew}", 'red')
        return False

    # check education
    needed_crew_education = {
        target_to_buy[car].education_f: target_to_buy[car].crew * count
        for car, count in to_buy.items()
    }
    for education, count in needed_crew_education.items():
        available = sum([1 for member in building.crew_members if member.education == education and member.available])
        if available < count:
            cprint(f"Missing {education}. Available: {available}, needed: {count}", 'red')
            return False

    return True


def _get_builder_schema(builder_schema):
    cprint('Loading builder schema...', 'cyan')
    with open(get_path(builder_schema), 'r') as f:
        builder_schema_raw = json.loads(f.read())
        return {key: VehicleTarget(**v) for key, v in builder_schema_raw.items()}


def _get_config(file_path, cmd_name):
    return get_config()['BUILDER']


def buy_needed_vehicles(driver, building, builder_schema, dry_run):
    cprint(f'Analyzing vehicles... {building}', 'yellow')
    to_buy = check_what_to_buy(building, builder_schema)

    if not to_buy:
        cprint(f"Nothing to buy.", 'green')
        return
    cprint(f"NEED to buy: {to_buy} {building}", 'yellow')

    is_crew_available = check_is_crew_available(building, builder_schema, to_buy)
    if not is_crew_available:
        cprint(
            f"NOT ENOUGH crew, skipping buying new vehicles... {building}",
            'red'
        )
        return

    cprint(f"GOT REQUIRED crew. {building}", 'green')

    needed_space = sum(to_buy.values())
    if needed_space > building.free_space:
        cprint(f"NEED MORE space, extending building... {building}", 'yellow')
        if not dry_run:
            expand_building(driver, building, needed_space - building.free_space)

    if not dry_run:
        buy_vehicles(driver, building, to_buy)


@click.command()
@click.option("--cpr", "cpr", type=click.STRING)
@click.option("--headless", "headless", default=True, type=click.BOOL)
@click.option("--limit", "limit", default=0, type=click.INT)
@click.option("--dry-run", "dry_run", default=False, is_flag=True, type=click.BOOL)
@click.option("--dont-buy", "dont_buy", default=False, is_flag=True, type=click.BOOL)
@click.option("--dont-assign", "dont_assign", default=False, is_flag=True, type=click.BOOL)
@click.option("--builder-schema", "builder_schema", type=click.STRING, default='builder_schema.json')
@click_config_file.configuration_option(provider=_get_config)
def builder(cpr, headless, limit, dry_run, dont_buy, dont_assign, builder_schema):
    builder_schema = _get_builder_schema(builder_schema)
    vehicles_keys = builder_schema.keys()
    driver = init_and_log_in(headless)
    buildings = get_list_of_buildings(driver, cpr)

    if limit > 0:
        cprint(f"LIMIT setting: {limit}", 'red')
        buildings = buildings[:limit]

    if dry_run:
        cprint("Running in dry-run mode.", 'red')

    buildings_len = len(buildings)
    for i, building in enumerate(buildings, start=1):
        text = f'----- WORKING ON {building} {i} of {buildings_len} -----'
        cprint('-'*len(text), 'magenta')
        cprint(text, 'magenta')
        cprint('-' * len(text), 'magenta')
        try:
            get_crew_members(driver, building)
            get_building_details(driver, building)

            # buy cars - check needed cars and needed crew
            if not dont_buy:
                buy_needed_vehicles(driver, building, builder_schema, dry_run)
            else:
                cprint('Skipping vehicles checks.', 'yellow')

            if not dont_assign:
                cprint(f'Assigning crew... {building}', 'yellow')
                # refresh details to get new vehicles list
                get_building_details(driver, building)

                # assign crew
                for vehicle in building.vehicles:
                    if vehicle.name in vehicles_keys:
                        assign_crew(driver, vehicle, builder_schema[vehicle.name], dry_run)
            else:
                cprint('Skipping assigning crew.', 'yellow')
        except Exception as err:
            file = get_path(f'error_{building.id}_{datetime.now().strftime("%d%m%Y%H%M%S")}')
            driver.save_screenshot(f"{file}.png")
            cprint(f"Error in {building}", 'red')
            cprint(str(err), 'red')
            with open(f"{file}.txt", "w+") as f:
                f.write(str(dataclasses.asdict(building)))
                f.write(str(err))
                f.write(traceback.format_exc())
            cprint(f'Logs were saved into {file} png and txt file', 'red')



if getattr(sys, 'frozen', False):
    builder(sys.argv[1:])
