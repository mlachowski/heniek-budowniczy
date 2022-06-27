import dataclasses
import enum
import time
from copy import copy
from typing import Optional

import click
from utils import init_and_log_in, do_click
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
    buildings = _get_table_rows(driver, "building_table")

    parsed_buildings = list()

    for building in buildings:
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
                    int(level.text.strip()),
                    int(crew.text.strip()),
                    None,
                    None,
                    list(),
                    list(),
                    None,
                )
            )

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
        vehicles_parsed.append(Vehicle(a.text.strip(), a.get_attribute("href").split("/")[-1:][0]))
    building.vehicles = vehicles_parsed


def buy_vehicles(driver, building, to_buy):
    driver.get(f"{BUILDING_BASE_URL}{building.id}/vehicles/new")
    for car, count in to_buy.items():
        for _ in range(0, count):
            vehicle = _find_vehicle(driver, car)
            if vehicle:
                do_click(driver, vehicle)


def get_crew_members(driver, building):
    driver.get(f"{BUILDING_BASE_URL}{building.id}/personals")

    crew_members = _get_table_rows(driver, "personal_table")
    crew_members_parsed = list()
    available_crew = 0
    for crew_member in crew_members:
        name, education, assigned, state, _ = list(crew_member.find_elements(By.TAG_NAME, "td"))
        crew_member_parsed = CrewMember(
            name=name.text.strip(),
            education=frozenset(education.text.strip().split(",")),
            assigned=assigned.text.strip(),
            state=state.text.strip(),
            available=state.text.strip() == "Dostępne" and assigned.text.strip() == "",
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
    for vehicle in driver.find_elements(By.CLASS_NAME, "vehicle_type"):
        if vehicle.find_element(By.TAG_NAME, "h3").text.strip() == vehicle_name:
            return list(vehicle.find_elements(By.TAG_NAME, "a"))[1]
    do_click(driver, driver.find_element(By.XPATH, '//*[@id="tabs"]/li[2]/a'))
    time.sleep(0.2)
    for vehicle in driver.find_elements(By.CLASS_NAME, "vehicle_type"):
        if vehicle.find_element(By.TAG_NAME, "h3").text.strip() == vehicle_name:
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
        print(f"WOULD LIKE to assign {to_assign}, education: {target_education}", vehicle.id, vehicle.name)
        for person in personal_table:
            if to_assign <= 0:
                return

            _, education, state, assign = list(person.find_elements(By.TAG_NAME, "td"))
            education = frozenset(education.text.strip().split(','))
            state = state.text.strip()
            assigned = assign.text.strip() != "Przydziel pojazd"
            if education == target_education and state == "Dostępne" and not assigned:
                if not dry_run:
                    do_click(driver, assign.find_element(By.TAG_NAME, "a"))
                    time.sleep(0.3)
                to_assign -= 1
        print('CANT assign all crew', vehicle.id, vehicle.name)
    else:
        print("NO NEED to assign", vehicle.name, vehicle.id)


def check_is_crew_available(building, target_to_buy, to_buy):
    needed_crew = sum(
        [
            target_to_buy[car].crew * count
            for car, count in to_buy.items()
            if target_to_buy[car].education is None
        ]
    )
    if building.available_crew and building.available_crew < needed_crew:
        print(f"Missing crew. Available: {building.available_crew}, needed: {needed_crew}")
        return False

    # check education
    needed_crew_education = {
        target_to_buy[car].education_f: target_to_buy[car].crew * count
        for car, count in to_buy.items()
        if target_to_buy[car].education
    }
    for education, count in needed_crew_education.items():
        available = sum([1 for member in building.crew_members if member.education == education])
        if available < count:
            print(f"Missing {education}. Available: {available}, needed: {count}")
            return False

    return True


# number of vehicles to buy, crew to assign
VEHICLES_TO_BUY = {
    "GCBARt": VehicleTarget(count=6, crew=2, education=None),
    "SD": VehicleTarget(count=1, crew=1, education=None),
    "SLOp": VehicleTarget(count=1, crew=1, education=None),
    "SRChem": VehicleTarget(count=2, crew=3, education=['Ratownictwo chemiczne'])
}


@click.command()
@click.option("--cpr", "cpr", type=click.STRING)
@click.option("--headless", "headless", default=True, type=click.BOOL)
@click.option("--limit", "limit", default=0, type=click.INT)
@click.option("--dry-run", "dry_run", default=False, is_flag=True, type=click.BOOL)
@click.option("--dont-buy", "dont_buy", default=False, is_flag=True, type=click.BOOL)
def builder(cpr, headless, limit, dry_run, dont_buy):
    vehicles_keys = VEHICLES_TO_BUY.keys()

    driver = init_and_log_in(headless)
    buildings = get_list_of_buildings(driver, cpr)

    if limit > 0:
        print(f"LIMIT", limit)
        buildings = buildings[:limit]

    for building in buildings:
        try:
            get_crew_members(driver, building)
            get_building_details(driver, building)

            # buy cars - check needed cars and needed crew
            to_buy = check_what_to_buy(building, VEHICLES_TO_BUY)
            is_crew_available = check_is_crew_available(building, VEHICLES_TO_BUY, to_buy)

            if is_crew_available:
                print("GOT REQUIRED crew", building.id, building.name)

                needed_space = sum(to_buy.values())
                if needed_space > building.free_space and not dont_buy:
                    print("NEED MORE space", building.id, building.name)
                    if not dry_run:
                        expand_building(driver, building, needed_space - building.free_space)
                if to_buy and not dont_buy:
                    print("WOULD like to buy", to_buy, building.name)
                    if not dry_run:
                        buy_vehicles(driver, building, to_buy)
            else:
                print(
                    f"NOT ENOUGH crew",
                    building.id,
                    building.name,
                )

            # assign crew
            for vehicle in building.vehicles:
                if vehicle.name in vehicles_keys:
                    assign_crew(driver, vehicle, VEHICLES_TO_BUY[vehicle.name], dry_run)
        except Exception as err:
            print(err)
            print(building)
