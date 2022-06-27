# Setup
`python3 -m venv operator`
`python setup.py develop`

Ustawianie loginu i hasła:

stare cmd
`setx LOGIN "login"`
`setx PASSWORD "haslo"`

powershell
`$env:LOGIN = "login"`
`$env:PASSWORD = "haslo"`

# Jak uruchomic
`builder --cpr <id_cpr>`

## Opcje
`--headless=False/True`
headless pokazuje lub nie przeglądarkę w której bot klika

`--dry-run` uruchamia, ale nie będzie nic kupować - dobre do sprawdzenia na początek

`--limit=5` określa limit remiz branych pod uwagę - np. 5, domyślnie leci wszystkie

`--dont-buy` opcja, żeby zablokować kupowanie aut i powiększanie remiz - będzie tylko przypisywać załogę

# Uruchomienie późniejsze:
linux
`source operator/bin/activate`

windows `operator/Scripts/activate.bat`