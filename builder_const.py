import dataclasses
import enum
from configparser import ConfigParser
from typing import Optional


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
