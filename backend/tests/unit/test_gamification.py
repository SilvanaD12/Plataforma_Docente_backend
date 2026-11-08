"""HU-051: nivel y puntos de cada ítem según su dificultad, e insignia según el porcentaje obtenido."""

from platform5e.domain.generation.gamification import badge_for, by_level, item_level


def test_level_and_points_come_from_the_difficulty_of_the_request():
    basic = item_level({"params": {"difficulty": "basica"}})
    assert (basic.title, basic.points) == ("Nivel 1 · Básico", 10)
    assert item_level({"params": {"difficulty": "avanzada"}}).points == 30
    assert item_level({"params": {"difficulty": "advanced"}}).number == 3  # valores ya migrados al inglés
    assert item_level({}).title == "Nivel 2 · Intermedio"  # recursos sin parámetros
    assert item_level({"params": {"difficulty": "otra"}}).number == 2


def test_badges_by_percent():
    assert [badge_for(p) for p in (100, 90, 89.9, 75, 60, 59.9, 0)] == ["Oro", "Oro", "Plata", "Plata", "Bronce", None, None]


def test_items_are_grouped_from_level_one_keeping_their_order():
    items = [
        {"id": "a", "params": {"difficulty": "avanzada"}},
        {"id": "b", "params": {"difficulty": "basica"}},
        {"id": "c"},
        {"id": "d", "params": {"difficulty": "basica"}},
    ]
    assert [(level.number, [i["id"] for i in group]) for level, group in by_level(items)] == [
        (1, ["b", "d"]),
        (2, ["c"]),
        (3, ["a"]),
    ]
