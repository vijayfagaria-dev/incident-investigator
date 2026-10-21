import math
from random import Random


class RandomStreams:
    """Independent, reproducible random generators, one per purpose.

    Keying each stream by what it draws (one metric, one node's logs, one effect) means
    editing a single effect does not reshuffle the noise drawn for everything else.
    """

    def __init__(self, seed: int) -> None:
        self._seed = seed

    def stream(self, *purpose: str) -> Random:
        return Random("/".join((str(self._seed), *purpose)))


def poisson(rng: Random, mean: float) -> int:
    """Poisson-distributed count, with a normal approximation for large means."""
    if mean > 30:
        return max(0, round(rng.gauss(mean, math.sqrt(mean))))
    threshold, count, product = math.exp(-mean), 0, rng.random()
    while product > threshold:
        count += 1
        product *= rng.random()
    return count
