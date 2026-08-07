"""Run the doctests in the package so the README-facing examples stay true."""

import doctest

import schemadrift


def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(schemadrift))
    return tests
