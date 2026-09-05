"""A very small pytest stand-in.

The test file is written against the pytest API. If pytest is installed it is
used; if not, this provides just enough of it (fixtures, parametrize, raises,
monkeypatch) that `python tests/run.py` works anywhere Python does. That keeps
the project runnable with zero install, without locking the tests to a
home-grown framework.
"""
from __future__ import annotations

import inspect
import traceback


class MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        old = getattr(target, name)
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)
        self._undo.clear()


class _Mark:
    @staticmethod
    def parametrize(argnames, argvalues):
        names = [n.strip() for n in argnames.split(",")]

        def deco(fn):
            fn._params = (names, list(argvalues))
            return fn
        return deco


class _Pytest:
    mark = _Mark()

    @staticmethod
    def fixture(*dargs, **dkwargs):
        def deco(fn):
            fn._fixture = True
            fn._autouse = dkwargs.get("autouse", False)
            return fn
        if dargs and callable(dargs[0]):
            return deco(dargs[0])
        return deco

    class raises:
        def __init__(self, exc):
            self.exc = exc

        def __enter__(self):
            return self

        def __exit__(self, t, v, tb):
            if t is None:
                raise AssertionError(f"{self.exc.__name__} not raised")
            return issubclass(t, self.exc)


pytest = _Pytest()


def run_module(mod) -> int:
    """Execute every test_* function in a module. Returns the failure count."""
    autouse = [v for v in vars(mod).values()
               if callable(v) and getattr(v, "_fixture", False)
               and getattr(v, "_autouse", False)]
    tests = [(n, v) for n, v in sorted(vars(mod).items())
             if n.startswith("test_") and callable(v)]

    passed = failed = 0
    failures = []

    for name, fn in tests:
        params = getattr(fn, "_params", None)
        cases = []
        if params:
            names, values = params
            for row in values:
                row = row if isinstance(row, (tuple, list)) else (row,)
                cases.append(dict(zip(names, row)))
        else:
            cases.append({})

        for kwargs in cases:
            mp = MonkeyPatch()
            gens = []
            try:
                for fx in autouse:
                    sig = inspect.signature(fx)
                    args = {"monkeypatch": mp} if "monkeypatch" in sig.parameters else {}
                    res = fx(**args)
                    if inspect.isgenerator(res):
                        next(res)
                        gens.append(res)

                sig = inspect.signature(fn)
                if "monkeypatch" in sig.parameters:
                    kwargs = {**kwargs, "monkeypatch": mp}
                fn(**kwargs)
                passed += 1
            except Exception:                                # noqa: BLE001
                failed += 1
                label = f"{name}{kwargs if kwargs else ''}"
                failures.append((label, traceback.format_exc()))
            finally:
                for g in gens:
                    try:
                        next(g)
                    except StopIteration:
                        pass
                mp.undo()

    for label, tb in failures:
        print(f"\nFAIL {label}\n{tb}")
    print(f"\n{passed} passed, {failed} failed")
    return failed
