"""Packaged authority-domain data for source-quality scoring.

This module exists solely so ``web_research.features.ranking.data`` is an
importable package — that lets ``importlib.resources.files(...)`` resolve
``authority_domains.txt`` both in the source tree and inside an installed
wheel (hatchling ships subpackages, not bare data dirs).
"""
