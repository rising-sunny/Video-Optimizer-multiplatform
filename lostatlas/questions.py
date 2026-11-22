"""Banco de preguntas. Pistas de la mas dificil a la mas facil (la ultima suele regalar la capital).

OJO: `verified` es False hasta pasar por la verificacion de hechos del pipeline antes de publicar.
Cada pista debe caber en ~35 caracteres (letra mono).
"""

GEO_DEMO = [
    dict(country="Italy", verified=False, clues=[
        "Two countries sit inside its borders",
        "Volcanoes: Vesuvius and Etna",
        "Capital: Rome"]),
    dict(country="Egypt", verified=False, clues=[
        "Most people live along one river",
        "Home of the Great Pyramid of Giza",
        "Capital: Cairo"]),
    dict(country="Japan", verified=False, clues=[
        "More than 14,000 islands",
        "Highest peak: Mount Fuji, 3,776 m",
        "Capital: Tokyo"]),
    dict(country="Madagascar", verified=False, clues=[
        "Most wildlife is found nowhere else",
        "The world's 4th largest island",
        "Capital: Antananarivo"]),
    dict(country="Kazakhstan", verified=False, clues=[
        "World's largest landlocked country",
        "It hosts the Baikonur Cosmodrome",
        "Capital: Astana"]),
]
