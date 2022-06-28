from setuptools import setup

setup(
    name="or_runner",
    version="0.1.0",
    py_modules=["runner"],
    install_requires=[
        "webdriver_manager",
        "selenium",
        "click",
        "requests",
        "unidecode",
        "click_config_file",
        "termcolor",
    ],
    entry_points={
        "console_scripts": [
            # 'runner = runner:runner',
            "builder = builder:builder",
        ],
    },
)
