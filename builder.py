import dataclasses
import enum
import json
import os
import sys
import time
import traceback
from configparser import ConfigParser
from copy import copy
from typing import Optional, List
from datetime import datetime

import click
import click_config_file
from termcolor import cprint
from utils import init_and_log_in, do_click, get_path, get_config, normalize, printProgressBar
from selenium.webdriver.common.by import By


BUILDING_BASE_URL = "https://www.operatorratunkowy.pl/buildings/"
VEHICLE_BASE_URL = "https://www.operatorratunkowy.pl/vehicles/"


class BuildingCategory(str, enum.Enum):
    OPI = "Building_polizeiwache"
    MEDIC = "Building_rettungswache"
    MEDIC_HELI = "Building_helipad"
    OPI_HELI = "Building_helipad_polizei"
    OPP = "Building_bereitschaftspolizei"
    SM = "Building_municipal_police"
    JRG = "Building_fire"


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


class VehicleCategory(enum.Enum):
    car = 0
    trailer = 1
    container = 2


@dataclasses.dataclass
class VehicleTarget:
    count: int
    crew: int
    education: Optional[list]
    category: VehicleCategory

    @property
    def education_f(self):
        return frozenset(self.education or [''])


@dataclasses.dataclass
class Config:
    cpr: int
    headless: bool
    builder_schema: dict
    builder_schema_file: str
    dry_run: bool
    dont_buy: bool
    dont_assign: bool
    start: int
    limit: int
    crew_min: int
    crew_max: int
    level_min: int
    level_max: int
    dont_recruit: bool
    dont_build_expansions: bool
    building_category: BuildingCategory
    ini: ConfigParser


def get_list_of_buildings(driver, cpr, building_category=BuildingCategory.JRG):
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
        if building_type == building_category.value:
            building_id = (
                name.find_element(By.TAG_NAME, "a").get_attribute("href").split("/")[-1:][0]
            )
            parsed_buildings.append(
                Building(
                    building_id,
                    name.text.strip(),
                    cpr,
                    building_category,
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
    vehicle_tabs = driver.find_elements(By.XPATH, '//*[@id="tabs"]/li/a')
    for tab in vehicle_tabs:
        do_click(driver, tab)
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


def assign_crew_to_vehicles(driver, building: Building, config: Config) -> None:
    vehicles_keys = config.builder_schema.keys()
    for vehicle in building.vehicles:
        if vehicle.name in vehicles_keys:
            assign_crew(driver, vehicle, config.builder_schema[vehicle.name], config.dry_run)


def assign_crew(driver, vehicle, vehicle_target_data, dry_run):
    if vehicle_target_data.crew == 0:
        return

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
    needed_crew_education = {
        target_to_buy[car].education_f: target_to_buy[car].crew * count
        for car, count in to_buy.items() if target_to_buy[car].category is VehicleCategory.car
    }
    for education, count in needed_crew_education.items():
        available = sum([1 for member in building.crew_members if member.education == education and member.available])
        if available < count:
            cprint(f"Missing {education}. Available: {available}, needed: {count}", 'red')
            return False

    return True


def _get_builder_schema(builder_schema: str) -> dict:
    cprint('Loading builder schema...', 'cyan')
    with open(get_path(builder_schema), 'r') as f:
        builder_schema_raw = json.loads(f.read())
        return {key: _get_vehicle_target(v) for key, v in builder_schema_raw.items()}


def _get_vehicle_target(config: dict) -> VehicleTarget:
    keys = config.keys()
    if 'category' not in keys:
        return VehicleTarget(**config, category=VehicleCategory.car)
    return VehicleTarget(count=config['count'], crew=0, education=None, category=VehicleCategory[config['category']])


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

    needed_space = sum([
        count for key, count in to_buy.items() if builder_schema[key].category is not VehicleCategory.container
    ])
    if needed_space > building.free_space:
        cprint(f"NEED MORE space, extending building... {building}", 'yellow')
        if not dry_run:
            expand_building(driver, building, needed_space - building.free_space)

    if not dry_run:
        buy_vehicles(driver, building, to_buy)


def filter_buildings(config: Config, buildings: List[Building]) -> List[Building]:
    if config.start > 0:
        cprint(f"START setting: {config.limit}", 'red')
        buildings = buildings[config.start:]

    if config.limit > 0:
        cprint(f"LIMIT setting: {config.limit}", 'red')
        buildings = buildings[:config.limit]

    return [building for building in buildings if _can_apply_building(config, building)]


def _can_apply_building(config: Config, building: Building) -> bool:
    checks = []
    if config.crew_min:
        checks.append(building.crew >= config.crew_min)
    if config.crew_max:
        checks.append(building.crew <= config.crew_max)
    if config.level_min:
        checks.append(building.level >= config.level_min)
    if config.level_max:
        checks.append(building.level <= config.level_max)
    return all(checks)


def set_recruitment(driver, buildings: List[Building], config: Config) -> None:
    cprint('Loading building list for setting recruitment...', 'yellow')
    driver.get(f"{BUILDING_BASE_URL}{config.cpr}")
    do_click(driver, driver.find_element(By.XPATH, '//*[@id="tabs"]/li[4]/a'))
    time.sleep(2)
    buildings_table = list(_get_table_rows(driver, "building_table"))
    try:
        recruitment_level = int(config.ini['RECRUITMENT']['duration'])
    except ValueError:
        recruitment_level = 4
    target_crew = config.ini['RECRUITMENT']['target_crew']

    building_ids = [building.id for building in buildings]
    for building in buildings_table:
        _, name, _, recruitment, _, set_target_crew, _ = list(building.find_elements(By.TAG_NAME, "td"))
        building_id = (
            name.find_element(By.TAG_NAME, "a").get_attribute("href").split("/")[-1:][0]
        )
        if building_id in building_ids:
            if "Brak" in normalize(recruitment):
                cprint(f'Would like to set recruitment level {recruitment_level} for {name.text.strip()}', 'yellow')
                if not config.dry_run:
                    do_click(driver, recruitment.find_element(By.XPATH, f'./div/a[{recruitment_level}]'))
                    time.sleep(0.3)
                    cprint(f'Recruitment level set {recruitment_level} for {name.text.strip()}', 'green')
            if normalize(set_target_crew) != target_crew:
                cprint(f'Would like to set target crew {target_crew} for {name.text.strip()}', 'yellow')
                if not config.dry_run:
                    do_click(driver, set_target_crew.find_element(By.CLASS_NAME, 'personal_count_target_edit_button'))
                    time.sleep(0.3)
                    input = set_target_crew.find_element(By.ID, 'building_personal_count_target')
                    input.clear()
                    input.send_keys(target_crew)
                    do_click(driver, set_target_crew.find_element(By.CLASS_NAME, 'btn-success'))
                    time.sleep(0.3)
                    cprint(f'Set crew target {target_crew} for {name.text.strip()}', 'green')
    cprint(f'Recruitment done', 'green')


@click.command()
@click.option("--cpr", "cpr", type=click.STRING)
@click.option("--headless", "headless", default=True, type=click.BOOL)
@click.option("--limit", "limit", default=0, type=click.INT)
@click.option("--start", "start", default=0, type=click.INT)
@click.option("--dry-run", "dry_run", default=False, is_flag=True, type=click.BOOL)
@click.option("--dont-buy", "dont_buy", default=False, is_flag=True, type=click.BOOL)
@click.option("--dont-assign", "dont_assign", default=False, is_flag=True, type=click.BOOL)
@click.option("--dont-build-expansions", "dont_build_expansions", default=False, is_flag=True, type=click.BOOL)
@click.option("--dont-recruit", "dont_recruit", default=False, is_flag=True, type=click.BOOL)
@click.option("--builder-schema", "builder_schema", type=click.STRING, default='builder_schema.json')
@click.option("--crew-min", "crew_min", default=0, type=click.INT)
@click.option("--crew-max", "crew_max", default=0, type=click.INT)
@click.option("--level-min", "level_min", default=0, type=click.INT)
@click.option("--level-max", "level_max", default=0, type=click.INT)
@click.option("--building-category", "building_category", type=click.STRING, default='JRG')
@click_config_file.configuration_option(provider=_get_config)
def builder(**kwargs):
    building_category = BuildingCategory[kwargs.pop('building_category')]
    builder_schema_file = kwargs.pop('builder_schema')
    config = Config(
        **kwargs,
        building_category=building_category,
        ini=get_config(),
        builder_schema_file=builder_schema_file,
        builder_schema=_get_builder_schema(builder_schema_file),
    )

    driver = init_and_log_in(config.headless)
    all_buildings = get_list_of_buildings(driver, config.cpr, config.building_category)
    cprint(f'Loaded {len(all_buildings)} of type {config.building_category.name}', 'green')

    buildings = filter_buildings(config, all_buildings)
    cprint(f'Filtered buildings {len(buildings)}', 'green')

    if config.dry_run:
        cprint("Running in dry-run mode.", 'red')

    if not config.dont_recruit:
        set_recruitment(driver, buildings, config)
    else:
        cprint('Skipping recruitment process.', 'yellow')

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
            if not config.dont_buy:
                buy_needed_vehicles(driver, building, config.builder_schema, config.dry_run)
            else:
                cprint('Skipping vehicles checks.', 'yellow')

            if not config.dont_assign:
                cprint(f'Assigning crew... {building}', 'yellow')
                # refresh details to get new vehicles list
                get_building_details(driver, building)

                # assign crew
                assign_crew_to_vehicles(driver, building, config)
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
