"""The generated input layer must match the SDL: edit api/schema/*.graphql, then run
`poetry run python -m api.codegen.generate` and commit the result."""
import pytest

from api.codegen import generate


def test_generated_inputs_are_current():
    assert generate.main(["--check"]) == 0, "api/gql/generated/inputs.py is stale"


def test_generation_is_deterministic():
    assert generate.generate() == generate.generate()


def test_check_flags_a_stale_file(tmp_path, monkeypatch):
    stale = tmp_path / "inputs.py"
    stale.write_text("# old\n")
    monkeypatch.setattr(generate, "OUT", stale)
    assert generate.main(["--check"]) == 1


def test_generated_models_follow_the_sdl():
    from api.gql.generated import inputs as g
    r = g.DateRange.model_validate({"from": "2026-01-01", "to": "2026-02-01"})
    assert r.from_.isoformat() == "2026-01-01"
    assert g.QueryTransactionsArgs().order_by == g.TransactionOrder.DATE_DESC
    with pytest.raises(Exception):
        g.DateRange.model_validate({"bogus": 1})
