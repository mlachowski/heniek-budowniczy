import time
from configparser import ConfigParser, SectionProxy
from contextlib import suppress
from enum import Enum
from typing import Optional

from builder_const import Building, Config, BuildingCategory, BUILDING_BASE_URL
from selenium.common import NoSuchElementException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from termcolor import cprint
from utils import do_click, get_table_rows


class ExpansionStatus(Enum):
    to_build = 0
    done = 1
    in_progress = 2
    waiting_other = 3
    other = 4


class Expansions(str, Enum):
    rsd = "Rozbudowa o stanowisko dowodzenia"
    prisoner_van = "Rozbudowa o policyjne więźniarki"
    opp = "Rozbudowa o Oddział Prewencji Policji"
    wrd = "Rozbudowa o Wydział Ruchu Drogowego"
    prison_cells = "Cele"
    prison_cell_1 = "Cela więzienna"
    prison_cell_n = "Dodatkowa cela"
    pr = "Rozbudowa dla pojazdów proszkowych"
    containers = "Rozbudowa dla kontenerów"


def build_expansions(driver: WebDriver, building: Building, config: Config) -> None:
    driver.get(f"{BUILDING_BASE_URL}{building.id}")
    expansions_target_raw = config.ini[building.category.name]
    expansions_target = {k: _get_expansion_target_value(v) for k, v in expansions_target_raw.items()}

    do_click(driver, driver.find_element(By.XPATH, '//*[@id="tabs"]/li[2]/a'))
    time.sleep(0.3)

    current_expansions = get_expansions_status(driver)
    cprint(f'Current: {current_expansions}, target: {expansions_target}', 'yellow')
    to_build = {k: max(0, v - current_expansions.get(k, 0)) for k, v in expansions_target.items()}
    cprint(f'To build: {to_build}', 'yellow')

    while sum(to_build.values()) > 0:
        result = queue_expansions(driver, to_build)
        if not result:
            break


def _get_expansion_target_value(value: str) -> int:
    if value == 'False':
        return 0
    if value == 'True':
        return 1
    return int(value)


def _get_expansion(name: WebElement) -> Optional[Expansions]:
    with suppress(ValueError):
        parsed = name.find_element(By.TAG_NAME, 'b').get_attribute('innerHTML').strip()
        expansions = Expansions(parsed)
        if expansions == Expansions.prison_cell_n or expansions == expansions.prison_cell_1:
            return Expansions.prison_cells
    return None


def _get_status(actions: WebElement) -> ExpansionStatus:
    try:
        action_href = actions.find_element(By.TAG_NAME, 'a').get_attribute('href')
        if 'extension_cancel' in action_href:
            return ExpansionStatus.in_progress
        if 'extension_finish' in action_href:
            return ExpansionStatus.in_progress
        if 'extension_ready' in action_href:
            return ExpansionStatus.done
        if 'extension/credits' in action_href:
            return ExpansionStatus.to_build
    except NoSuchElementException:
        if "Pozostały czas" in actions.text:
            return ExpansionStatus.in_progress

    try:
        if "Pozostały czas" in actions.get_attribute('text'):
            return ExpansionStatus.in_progress
    except Exception as err:
        pass
    return ExpansionStatus.waiting_other


def get_expansions_status(driver: WebDriver) -> dict:
    rows = get_table_rows(driver, class_name="table")
    already_built = {}
    for row in rows:
        name, _, _, actions = row.find_elements(By.TAG_NAME, 'td')
        expansion = _get_expansion(name)
        if not expansion:
            continue

        expansion_status = _get_status(actions)
        if expansion_status in [ExpansionStatus.done, ExpansionStatus.in_progress]:
            already_built[expansion.name] = already_built.get(expansion.name, 0) + 1

    return already_built


def queue_expansions(driver: WebDriver, to_build: dict) -> bool:
    rows = get_table_rows(driver, class_name="table")
    for row in rows:
        name, _, _, actions = row.find_elements(By.TAG_NAME, 'td')
        expansion = _get_expansion(name)
        print(name, expansion)
        if not expansion:
            continue

        expansion_status = _get_status(actions)
        print(expansion_status, to_build.get(expansion.name), actions.text)
        if expansion_status is ExpansionStatus.to_build and to_build.get(expansion.name, 0) > 0:
            to_build[expansion.name] = to_build[expansion.name] - 1
            do_click(driver, actions.find_element(By.TAG_NAME, 'a'))
            cprint(f'Expansion was queued {expansion}', 'green')
            return True

    return False
