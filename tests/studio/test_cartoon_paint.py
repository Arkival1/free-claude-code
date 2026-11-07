"""Painted cartoons: places and characters painted once, cut out, kept, and
acted out on the stage."""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from free_claude_code.studio.farm.animated import paint_cartoon, setting_of
from free_claude_code.studio.farm.cartoon.aiart import (
    ArtBook,
    Sprites,
    cut_out,
    mouth_only,
)
from free_claude_code.studio.farm.cartoon.heads import Look
from free_claude_code.studio.farm.cartoon.puppet import Placed, draw_figure
from free_claude_code.studio.farm.cartoon.scene import CartoonShot, paint
from free_claude_code.studio.farm.cartoon.screenplay import parse_screenplay
from free_claude_code.studio.models import FarmCharacter


def figure(
    size: tuple[int, int], *, mouth: bool = False, colour=(40, 90, 200)
) -> Image.Image:
    """A character on a plain white page, as the painter is asked for."""
    w, h = size
    picture = Image.new("RGB", size, (250, 250, 250))
    d = ImageDraw.Draw(picture)
    d.ellipse(
        (w * 0.4, h * 0.08, w * 0.6, h * 0.25),
        fill=(240, 200, 170),
        outline=(0, 0, 0),
        width=3,
    )
    d.rectangle(
        (w * 0.42, h * 0.25, w * 0.58, h * 0.6), fill=colour, outline=(0, 0, 0), width=3
    )
    d.rectangle(
        (w * 0.43, h * 0.6, w * 0.57, h * 0.92),
        fill=(60, 50, 40),
        outline=(0, 0, 0),
        width=3,
    )
    d.ellipse(
        (w * 0.45, h * 0.13, w * 0.48, h * 0.15), fill=(255, 255, 255)
    )  # a white eye
    if mouth:
        d.ellipse((w * 0.47, h * 0.19, w * 0.53, h * 0.23), fill=(90, 10, 30))
    return picture


def rgba(picture: Image.Image, at: tuple[int, int]) -> tuple[int, ...]:
    value = picture.getpixel(at)
    assert isinstance(value, tuple)
    return value


def load(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        return opened.copy()


class FakePainter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int, int], Path | None]] = []

    async def __call__(self, prompt, size, seed, out, start_from, strength):
        self.calls.append((prompt, size, start_from))
        out.parent.mkdir(parents=True, exist_ok=True)
        if size[0] > size[1]:
            Image.new("RGB", size, (30, 40, 120)).save(out)
        else:
            figure(size, mouth="open mouth" in prompt).save(out)
        return out


def test_the_plain_background_is_cut_away_but_white_eyes_stay(tmp_path):
    painted = tmp_path / "painted.png"
    figure((200, 300)).save(painted)
    cut = load(cut_out(painted, tmp_path / "cut.png"))
    assert cut.mode == "RGBA"
    assert cut.width < 200 and cut.height < 300  # cropped to the character
    alpha = cut.getchannel("A")
    assert alpha.getpixel((0, 0)) == 0
    # The white eye inside the head is not background.
    box = cut.getbbox()
    assert box is not None
    eye = (round(200 * 0.465) - box[0], round(300 * 0.14))
    assert (
        rgba(cut, (eye[0] - round(200 * 0.4) + 1, eye[1] - round(300 * 0.08)))[3] == 255
    )


def test_only_the_mouth_changes_while_talking(tmp_path):
    painted, talking = tmp_path / "a.png", tmp_path / "b.png"
    figure((200, 300)).save(painted)
    # The talking picture also moved a hand a little (img2img drift).
    moved = figure((200, 300), mouth=True)
    ImageDraw.Draw(moved).rectangle((100, 250, 110, 260), fill=(255, 0, 0))
    moved.save(talking)
    base = cut_out(painted, tmp_path / "base.png")
    talk = load(mouth_only(painted, talking, base, tmp_path / "talk.png"))
    still = load(base)
    assert talk.size == still.size
    diff = [
        (x, y)
        for y in range(talk.height)
        for x in range(talk.width)
        if rgba(talk, (x, y))[:3] != rgba(still, (x, y))[:3]
    ]
    assert diff, "the mouth opened"
    # Every change is up in the face, none down at the hand.
    assert max(y for _, y in diff) < talk.height * 0.3


@pytest.mark.asyncio
async def test_art_is_painted_once_and_kept(tmp_path):
    painter = FakePainter()
    book = ArtBook(tmp_path, "superhero", painter)
    place = await book.place("rooftop over the city at night")
    again = await book.place("rooftop over the city at night")
    assert place == again and len(painter.calls) == 1
    assert painter.calls[0][1] == (1344, 768)

    sprites = await book.character(
        "Kai", "a teen hero with spiky hair", feelings=("angry",)
    )
    assert sprites.base.is_file() and sprites.talk and sprites.talk.is_file()
    assert sprites.for_feeling("angry").name == "angry.png"
    assert sprites.for_feeling("sad") == sprites.base
    calls = len(painter.calls)
    # Talking and feelings start from the first painting (same character).
    assert all(start is not None for _, _, start in painter.calls[2:])
    await book.character("Kai", "a teen hero with spiky hair", feelings=("angry",))
    assert len(painter.calls) == calls


def test_a_painted_character_acts_on_the_stage(tmp_path):
    painted = tmp_path / "p.png"
    figure((200, 300)).save(painted)
    base = cut_out(painted, tmp_path / "base.png")
    sprites = Sprites(base=base, talk=base)
    look = Look(name="Kai", sprites=sprites)
    canvas = Image.new("RGB", (640, 360), (10, 120, 10))
    draw_figure(
        canvas,
        Placed(look=look, action="talk", x=0.5, facing=-1, speaking=True),
        t=0.3,
        length=2.0,
        ground=330,
        height=240,
    )
    colours = canvas.getcolors(100_000) or []
    assert any(c == (40, 90, 200) for _, c in colours), "the painted body shows"
    # A whole shot films with the painted place as the background.
    place = tmp_path / "place.png"
    Image.new("RGB", (1344, 768), (30, 40, 120)).save(place)
    shot = CartoonShot(
        place="night",
        picture=place,
        actors=(Placed(look=look, action="walk_in", x=0.5),),
        camera="wide",
    )
    frame = paint(shot, 0.4, 2.0, (640, 360))
    assert frame.size == (640, 360)
    assert all(
        abs(a - b) <= 3 for a, b in zip(rgba(frame, (5, 5)), (30, 40, 120), strict=True)
    )


@pytest.mark.asyncio
async def test_a_whole_cartoon_is_painted_with_only_the_feelings_it_needs(tmp_path):
    painter = FakePainter()
    book = ArtBook(tmp_path, "superhero", painter)
    kai = FarmCharacter(name="Kai", description="a teen hero", age="kid")
    scenes = [
        {
            "place": "night",
            "setting": "rooftop at night",
            "cast": [
                {"name": "Kai", "feel": "angry"},
                {"name": "Bolt", "action": "cheer"},
            ],
        },
        {
            "place": "night",
            "setting": "rooftop at night",
            "cast": [{"name": "Kai", "feel": ""}],
        },
        {"place": "city", "setting": "city street by day", "cast": []},
    ]
    looks, places = await paint_cartoon(
        book, [kai], {"kai": (Look(name="Kai"), "am_adam")}, scenes
    )
    assert set(places) == {"rooftop at night", "city street by day"}
    assert looks["kai"][1] == "am_adam"
    kai_art = looks["kai"][0].sprites
    assert isinstance(kai_art, Sprites)
    assert [f for f, _ in kai_art.feelings] == ["angry"]
    # A character the writer made up is painted too, happy for cheering.
    bolt = looks["bolt"][0].sprites
    assert isinstance(bolt, Sprites)
    assert [f for f, _ in bolt.feelings] == ["happy"]
    assert any("child" in prompt for prompt, _, _ in painter.calls)


def test_the_writer_says_where_each_shot_is():
    play = parse_screenplay(
        '{"shots": [{"place": "night", "setting": "a rooftop over the city", '
        '"say": "Look out!", "cast": [{"name": "Kai"}]}, {"say": "Too late."}]}',
        idea="x",
        cast_names=["Kai"],
    )
    shots = play["shots"]
    assert isinstance(shots, list)
    first, second = shots
    assert isinstance(first, dict) and isinstance(second, dict)
    assert setting_of(first) == "a rooftop over the city"
    assert second["setting"] == "a rooftop over the city"  # kept until it changes
