from setuptools import setup

setup(
    name="webcompat_scraper",
    version="2018.08.27",
    author="tdsmith",
    author_email="tdsmith@mozilla.com",
    description="Scrapes webcompat bugs from Github and Bugzilla for display.",
    packages=["scraper"],
    install_requires=[
        "attrs",
        "click",
        "github3.py",
        "pandas",
        "requests",
    ],
    extras_require={
        "test": [
            "pytest",
            "mypy",
        ]
    }
)
