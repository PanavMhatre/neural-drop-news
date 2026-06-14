"""Crypto/Web3 channel roster for targeted YouTube b-roll search."""
import random

# (handle, search_alias, weight)
CHANNELS = [
    ("@coinbureau",          "coin bureau crypto",                    3),
    ("@intothecryptoverse",  "benjamin cowen into the cryptoverse",   3),
    ("@AltcoinDailyio",      "altcoin daily crypto",                  3),
    ("@bankless",            "bankless podcast crypto",               3),
    ("@InvestAnswers",       "investanswers crypto",                  2),
    ("@thechartguys",        "the chart guys crypto",                 2),
    ("@CryptoBanter",        "crypto banter show",                    2),
    ("@RaoulGMI",            "raoul pal real vision crypto",          2),
    ("@APompliano",          "pomp podcast bitcoin",                  2),
    ("@ScottMelker",         "scott melker wolf of all streets",      2),
    ("@CryptoCasey",         "crypto casey explained",                1),
    ("@TheCryptoLark",       "lark davis crypto",                     1),
    ("@DigitalAssetNewss",   "digital asset news crypto",             1),
    ("@aantonop",            "andreas antonopoulos bitcoin",          1),
    ("@realvisioncrypto",    "real vision crypto podcast",            2),
    ("@UnchainedCrypto",     "unchained laura shin crypto",           2),
    ("@decryptmedia",        "decrypt crypto news",                   2),
]

# Minimum video duration in seconds (10 min = 600s)
MIN_DURATION_SECONDS = 600


def weighted_sample(n: int = 3) -> list[str]:
    """Return n channel search aliases sampled by weight (without replacement)."""
    population = [alias for _, alias, w in CHANNELS for _ in range(w)]
    seen = set()
    result = []
    random.shuffle(population)
    for alias in population:
        if alias not in seen:
            seen.add(alias)
            result.append(alias)
        if len(result) == n:
            break
    return result
