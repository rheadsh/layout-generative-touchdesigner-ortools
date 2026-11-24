import pytest

from editorial_solver import Block, Page, Weights, parse_relation, solve, validate_blocks

KW = dict(time_limit=1.0, workers=2)
OK = ("OPTIMAL", "FEASIBLE")


def by_id(res):
    return {b["id"]: b for b in res["blocks"]}


@pytest.mark.parametrize("seed", range(4))
def test_geometry_invariants(sample_blocks, page, seed):
    res = solve(sample_blocks, page, seed=seed, **KW)
    assert res["status"] in OK
    bs = res["blocks"]
    for b in bs:
        assert b["col"] >= 0 and b["row"] >= 0
        assert b["col"] + b["cols"] <= page.cols
        assert b["row"] + b["rows"] <= page.rows
    for i, a in enumerate(bs):
        for c in bs[i + 1 :]:
            overlap = (
                a["col"] < c["col"] + c["cols"]
                and c["col"] < a["col"] + a["cols"]
                and a["row"] < c["row"] + c["rows"]
                and c["row"] < a["row"] + a["rows"]
            )
            assert not overlap, (a["id"], c["id"])
            assert a["row"] * page.cols + a["col"] <= c["row"] * page.cols + c["col"]


def test_relations(sample_blocks, page):
    res = solve(sample_blocks, page, **KW)
    d = by_id(res)
    assert d["titular"]["row"] == 0
    cap, img = d["pie1"], d["foto1"]
    assert (cap["col"], cap["cols"]) == (img["col"], img["cols"])
    assert cap["row"] == img["row"] + img["rows"]


def test_fullwidth(page):
    blocks = [
        Block("a", "headline", rel=["top", "fullwidth"], max_h=2),
        Block("b", "image", min_w=3, min_h=3),
    ]
    d = by_id(solve(blocks, page, **KW))
    assert d["a"]["cols"] == page.cols and d["a"]["row"] == 0


def test_right_of(page):
    blocks = [
        Block("a", "image", min_w=3, max_w=4, min_h=3, max_h=4),
        Block("b", "text", min_w=2, max_w=4, rel=["right:a"]),
    ]
    d = by_id(solve(blocks, page, **KW))
    assert d["b"]["col"] == d["a"]["col"] + d["a"]["cols"]
    assert d["b"]["row"] == d["a"]["row"]


def test_text_capacity(sample_blocks, page):
    res = solve(sample_blocks, page, **KW)
    chars = {b.id: b.chars for b in sample_blocks}
    for b in res["blocks"]:
        assert b["cols"] * b["rows"] * page.chars_per_module >= chars[b["id"]]


def test_optional_dropped_required_kept(page):
    blocks = [
        Block("a", "image", min_w=12, min_h=10),
        Block("b", "image", min_w=12, min_h=5),
        Block("opt", "quote", min_w=12, min_h=4, required=False),
    ]
    res = solve(blocks, page, **KW)
    assert res["status"] in OK
    ids = {b["id"] for b in res["blocks"]}
    assert {"a", "b"} <= ids and "opt" not in ids


def test_infeasible_conflicts(page):
    blocks = [
        Block("a", "image", min_w=8, min_h=10),
        Block("b", "image", min_w=8, min_h=10),
        Block("c", "text", chars=60),
    ]
    res = solve(blocks, page, **KW)
    assert res["status"] == "INFEASIBLE"
    assert res["blocks"] == []
    assert res["conflicts"] == ["a", "b"]


@pytest.mark.parametrize(
    "blocks, msg",
    [
        ([Block("")], "falta id"),
        ([Block("a"), Block("a")], "duplicado"),
        ([Block("a", min_w=5, max_w=3)], "min_w .* > max_w"),
        ([Block("a", min_h=5, max_h=3)], "min_h .* > max_h"),
        ([Block("a", min_w=13)], "supera las 12 columnas"),
        ([Block("a", min_h=17)], "supera las 16 filas"),
        ([Block("a", rel=["fullwidth"], max_w=5)], "fullwidth exige"),
        ([Block("a", min_w=0)], "deben ser >= 1"),
        ([Block("a", max_w=-1)], "deben ser >= 0"),
        ([Block("a", priority=-1)], "no pueden ser negativos"),
        ([Block("a", chars=-1)], "no pueden ser negativos"),
        ([Block("a", kind="text", chars=100000)], "necesitan"),
        ([Block("a", rel=["foo"])], "relación desconocida"),
        ([Block("a", rel=["below"])], "relación desconocida"),
        ([Block("a", rel=["below:a"])], "a sí mismo"),
        ([Block("a", rel=["below:zz"])], "id inexistente"),
    ],
)
def test_validate_blocks_errors(page, blocks, msg):
    with pytest.raises(ValueError, match=msg):
        validate_blocks(blocks, page)
    with pytest.raises(ValueError, match=msg):
        solve(blocks, page, **KW)


@pytest.mark.parametrize(
    "kw, msg",
    [
        (dict(cols=0), "mayores que cero"),
        (dict(rows=0), "mayores que cero"),
        (dict(chars_per_module=0), "mayores que cero"),
        (dict(margin=-1), "negativos"),
        (dict(gutter=-1), "negativos"),
        (dict(row_gutter=-1), "negativos"),
        (dict(margin=600), "espacio útil"),
    ],
)
def test_page_validate(kw, msg):
    with pytest.raises(ValueError, match=msg):
        Page(**kw).validate()


@pytest.mark.parametrize("w", [dict(coverage=-1), dict(area=1.5)])
def test_weights_validate(w):
    with pytest.raises(ValueError, match="entero >= 0"):
        Weights(**w).validate()
    Weights().validate()


def test_parse_relation():
    assert parse_relation("below:foto1") == ("below", "foto1")
    assert parse_relation("top") == ("top", None)


def test_hint_resolve(sample_blocks, page):
    first = solve(sample_blocks, page, **KW)
    again = solve(sample_blocks, page, hint=first["blocks"], **KW)
    assert again["status"] in OK


def test_deterministic(sample_blocks, page):
    a = solve(sample_blocks, page, seed=1, deterministic=True, time_limit=1.0, workers=8)
    b = solve(sample_blocks, page, seed=1, deterministic=True, time_limit=1.0, workers=8)
    assert a["blocks"] == b["blocks"]


def test_pixel_conversion():
    page = Page(row_gutter=20.0)
    res = solve([Block("a", "image", min_w=4, min_h=3)], page, **KW)
    b = res["blocks"][0]
    g, gv = page.gutter, page.vertical_gutter
    assert b["x"] == pytest.approx(page.margin + b["col"] * (page.cell_w + g))
    assert b["y"] == pytest.approx(page.margin + b["row"] * (page.cell_h + gv))
    assert b["w"] == pytest.approx(b["cols"] * page.cell_w + (b["cols"] - 1) * g)
    assert b["h"] == pytest.approx(b["rows"] * page.cell_h + (b["rows"] - 1) * gv)


def test_conflicts_include_relation_targets(page):
    blocks = [
        Block("foto", "image", min_w=8, min_h=10),
        Block("pie", "caption", max_h=1, rel=["below:foto"]),
        Block("texto", min_w=8, min_h=10),
    ]
    res = solve(blocks, page, time_limit=1.0, workers=1)
    assert res["status"] == "INFEASIBLE"
    assert set(res["conflicts"]) >= {"foto", "texto"}
