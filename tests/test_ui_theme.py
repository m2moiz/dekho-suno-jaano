"""Light, dark, or follow the Mac, kept across launches (#116).

Read off the files the browser actually gets: the committed build under
dsj/ui/static/ is what `dsj ui` serves, so a theme script that is in ui/ but
not in the build, or that lands after the stylesheet, is caught here.
"""

from __future__ import annotations

import re
from pathlib import Path

from dsj.ui.server import STATIC

UI = Path(__file__).resolve().parent.parent / "ui"
THEME_CSS = UI / "src" / "styles" / "theme.css"


def built_css() -> str:
    (css,) = (STATIC / "assets").glob("*.css")
    return css.read_text()


def test_the_built_page_runs_the_theme_script_before_any_stylesheet() -> None:
    page = (STATIC / "index.html").read_text()
    script = page.find("dsj-theme")
    stylesheet = page.find('<link rel="stylesheet"')
    assert script != -1, "the built page carries no theme script"
    assert stylesheet != -1, "the built page links no stylesheet, so this checks nothing"
    assert script < stylesheet
    # Before the app's module too, so nothing paints before the scheme is set.
    assert script < page.find('<script type="module"')
    head_script = page[page.rfind("<script>", 0, script):page.find("</script>", script)]
    assert "document.cookie" in head_script
    assert "localStorage" not in head_script


def test_every_colour_is_written_once_for_both_schemes() -> None:
    css = THEME_CSS.read_text()
    assert "color-scheme: light dark;" in css
    assert css.count("light-dark(") >= 20


def lightness(colour: str) -> float:
    found = re.fullmatch(r"oklch\(\s*([\d.]+)(%?)\s.*\)", colour.strip())
    assert found, colour
    value = float(found[1])
    return value / 100 if found[2] else value


def test_dark_body_text_is_not_pure_white() -> None:
    """Near-white on near-black halates over an hour's reading (#57 section 11.3)."""
    css = THEME_CSS.read_text()
    found = re.search(r"--foreground:\s*light-dark\((oklch\([^)]*\)),\s*(oklch\([^)]*\))\)", css)
    assert found, "no light-dark() --foreground in theme.css"
    assert lightness(found[2]) < 0.95
    # And the light side really is the dark text, so the pair is not reversed.
    assert lightness(found[1]) < 0.5


def test_the_built_css_pins_a_chosen_scheme_by_attribute() -> None:
    """The build rewrites light-dark() into variables only a stylesheet can flip.

    Tailwind's Lightning CSS pass targets browsers older than light-dark(), so
    the shipped CSS carries `--lightningcss-light`/`-dark` pairs keyed on the
    `color-scheme` a RULE sets, and an inline style.colorScheme alone would
    move the scrollbars and leave every colour where it was. The data-theme
    rules are what make a choice of Dark paint dark; this holds them in the
    build, not only in the source.
    """
    css = built_css()
    for theme, light, dark in (("dark", " ", "initial"), ("light", "initial", " ")):
        rule = re.search(rf":root\[data-theme={theme}\]\{{([^}}]*)\}}", css)
        assert rule, f"no :root[data-theme={theme}] rule in the build"
        body = rule[1]
        assert f"color-scheme:{theme}" in body
        if "--lightningcss-" in css:
            assert f"--lightningcss-light:{light}" in body, body
            assert f"--lightningcss-dark:{dark}" in body, body


def test_the_dark_variant_follows_the_choice_and_the_mac() -> None:
    css = built_css()
    assert ":where([data-theme=dark],[data-theme=dark] *)" in css
    assert "@media (prefers-color-scheme:dark)" in css
    assert ".dark " not in css and ".dark{" not in css, "a leftover .dark class selector"
