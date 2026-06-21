"""Crypto/Web3 channel roster for targeted YouTube b-roll search."""
import random

# (handle, search_alias, weight)
# Weight 3 = top tier (millions of subs, daily crypto content, high production)
# Weight 2 = solid (consistent crypto analysis/news)
# Weight 1 = niche but quality
CHANNELS = [
    # ── Tier 1: Highest quality, most relevant b-roll ──────────────────────────
    ("@coinbureau",           "coin bureau crypto",                     3),
    ("@intothecryptoverse",   "benjamin cowen into the cryptoverse",    3),
    ("@AltcoinDailyio",       "altcoin daily crypto",                   3),
    ("@bankless",             "bankless podcast crypto",                3),
    ("@CryptoBanter",         "crypto banter show",                     3),
    ("@ScottMelker",          "scott melker wolf of all streets",       3),
    ("@APompliano",           "pomp podcast bitcoin",                   3),
    ("@RaoulGMI",             "raoul pal real vision crypto",           3),

    # ── Tier 2: Major news & analysis ──────────────────────────────────────────
    ("@decryptmedia",         "decrypt crypto news",                    2),
    ("@CoinDeskVideo",        "coindesk crypto news",                   2),
    ("@CoinTelegraph",        "cointelegraph crypto news",              2),
    ("@realvisioncrypto",     "real vision crypto",                     2),
    ("@UnchainedCrypto",      "unchained laura shin crypto",            2),
    ("@MessariCrypto",        "messari crypto research",                2),
    ("@InvestAnswers",        "investanswers crypto",                   2),
    ("@TheCryptoLark",        "lark davis crypto",                      2),
    ("@WatcherGuru",          "watcher guru crypto news",               2),
    ("@CryptosRUs",           "cryptos r us george crypto",             2),
    ("@DataDash",             "nicholas merten data dash crypto",       2),

    # ── Tier 3: Niche but high quality ─────────────────────────────────────────
    ("@aantonop",             "andreas antonopoulos bitcoin",           1),
    ("@DigitalAssetNewss",    "digital asset news crypto",              1),
    ("@CryptoCasey",          "crypto casey explained",                 1),
    ("@thechartguys",         "the chart guys technical analysis",      1),
    ("@a16zcrypto",           "a16z crypto web3",                       1),
    ("@GeminiTrust",          "gemini crypto exchange",                 1),
    ("@BitcoinMagazine",      "bitcoin magazine",                       1),
    ("@CryptoZombie",         "k crypto zombie altcoin",                1),
]

# Minimum video duration in seconds (10 min = 600s)
MIN_DURATION_SECONDS = 600


def weighted_sample(n: int = 5) -> list[str]:
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
