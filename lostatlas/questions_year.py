"""Quiz "Adivina el ano". year < 0 = a. C. Pistas de la mas dificil a la mas facil (<= 35 caracteres).

`verified` sigue en False hasta pasar por la verificacion de hechos del pipeline antes de publicar.
"""

YEAR_DEMO = [
    dict(year=1912, title="The sinking of the Titanic", verified=False, clues=[
        "Over 1,500 lives lost at sea",
        "Left Southampton bound for New York",
        "RMS Titanic sinks"]),
    dict(year=1789, title="The storming of the Bastille", verified=False, clues=[
        "Held just seven prisoners that day",
        "Date celebrated every 14 July",
        "Crowd storms the Bastille"]),
    dict(year=1969, title="Apollo 11 lands on the Moon", verified=False, clues=[
        "Launched on a Saturn V rocket",
        "Two men walk on another world",
        "Apollo 11 touches the Moon"]),
    dict(year=1453, title="The fall of Constantinople", verified=False, clues=[
        "Giant cannons batter ancient walls",
        "Sultan Mehmed II is 21 years old",
        "The Byzantine Empire falls"]),
    dict(year=-323, title="The death of Alexander the Great", verified=False, clues=[
        "He was only 32 years old",
        "His generals split the empire",
        "Alexander the Great dies"]),
]
