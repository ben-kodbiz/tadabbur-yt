"""Built-in Quran Surah dictionary.

Provides the canonical 114 surahs with aliases for robust matching against
titles and descriptions (English, Malay, romanized Arabic spellings).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Surah:
    number: int
    arabic: str
    transliteration: str  # canonical romanized name used as identifier
    english: str
    aliases: tuple[str, ...] = ()

    @property
    def canonical(self) -> str:
        return self.transliteration.lower().replace(" ", "-")


def _surah(
    number: int,
    arabic: str,
    transliteration: str,
    english: str,
    *aliases: str,
) -> Surah:
    return Surah(
        number=number,
        arabic=arabic,
        transliteration=transliteration,
        english=english,
        aliases=tuple(aliases),
    )


SURAHS: tuple[Surah, ...] = (
    _surah(1, "الفاتحة", "Al-Fatihah", "The Opening", "Al-Fatiha", "Al Fatihah", "Al-Fatihah"),
    _surah(2, "البقرة", "Al-Baqarah", "The Cow", "Al-Baqara", "Baqarah", "Al Baqarah"),
    _surah(3, "آل عمران", "Ali 'Imran", "Family of Imran", "Ali-Imran", "Ali Imran", "Aali Imran"),
    _surah(4, "النساء", "An-Nisa", "The Women", "An-Nisa'", "Nisa", "An Nisa"),
    _surah(5, "المائدة", "Al-Ma'idah", "The Table Spread", "Al-Maidah", "Al Maidah", "Maidah"),
    _surah(6, "الأنعام", "Al-An'am", "The Cattle", "Al-Anam", "Al Anam", "Anam"),
    _surah(7, "الأعراف", "Al-A'raf", "The Heights", "Al-Araf", "Al Araf"),
    _surah(8, "الأنفال", "Al-Anfal", "The Spoils of War", "Al-AnfAl", "Al Anfal", "Anfal"),
    _surah(9, "التوبة", "At-Tawbah", "The Repentance", "At-Taubah", "Tawbah", "Taubah"),
    _surah(10, "يونس", "Yunus", "Jonah", "Yunus"),
    _surah(11, "هود", "Hud", "Hud", "Hud"),
    _surah(12, "يوسف", "Yusuf", "Joseph", "Yusuf"),
    _surah(13, "الرعد", "Ar-Ra'd", "The Thunder", "Ar-Rad", "Ar Ra'd", "Ar Rad"),
    _surah(14, "إبراهيم", "Ibrahim", "Abraham", "Ibrahim"),
    _surah(15, "الحجر", "Al-Hijr", "The Rocky Tract", "Al-Hijr"),
    _surah(16, "النحل", "An-Nahl", "The Bee", "An-Nahl"),
    _surah(17, "الإسراء", "Al-Isra", "The Night Journey", "Al-Isra", "Al Isra", "Bani Israel"),
    _surah(18, "الكهف", "Al-Kahf", "The Cave", "Al-Kahfi", "Kahf", "Kahfi", "Al Kahf", "Al Kahfi"),
    _surah(19, "مريم", "Maryam", "Mary", "Maryam"),
    _surah(20, "طه", "Ta-Ha", "Ta-Ha", "Taha", "Ta Ha"),
    _surah(21, "الأنبياء", "Al-Anbiya", "The Prophets", "Al-Anbiya", "Anbiya", "Al Anbiya"),
    _surah(22, "الحج", "Al-Hajj", "The Pilgrimage", "Al-Haj", "Hajj", "Al Hajj"),
    _surah(23, "المؤمنون", "Al-Mu'minun", "The Believers", "Al-Muminun", "Muminun", "Al Mu'minun"),
    _surah(24, "النور", "An-Nur", "The Light", "An-Nur", "Nur", "An Nur"),
    _surah(25, "الفرقان", "Al-Furqan", "The Criterion", "Al-Furqan", "Furqan", "Al Furqan"),
    _surah(26, "الشعراء", "Ash-Shu'ara", "The Poets", "Ash-Shuara", "Shuara", "Asy-Syu'ara"),
    _surah(27, "النمل", "An-Naml", "The Ant", "An-Naml", "Naml", "An Naml"),
    _surah(28, "القصص", "Al-Qasas", "The Stories", "Al-Qasas", "Qasas", "Al Qasas"),
    _surah(29, "العنكبوت", "Al-'Ankabut", "The Spider", "Al-Ankabut", "Ankabut", "Al Ankabut"),
    _surah(30, "الروم", "Ar-Rum", "The Romans", "Ar-Rum", "Rum", "Ar Rum"),
    _surah(31, "لقمان", "Luqman", "Luqman", "Luqman"),
    _surah(32, "السجدة", "As-Sajdah", "The Prostration", "As-Sajda", "Sajdah", "As Sajdah"),
    _surah(33, "الأحزاب", "Al-Ahzab", "The Combined Forces", "Al-Ahzab", "Ahzab", "Al Ahzab"),
    _surah(34, "سبأ", "Saba", "Sheba", "Saba'", "Saba"),
    _surah(35, "فاطر", "Fatir", "The Originator", "Fatir", "Faatir"),
    _surah(36, "يس", "Ya-Sin", "Ya Sin", "Yasin", "Ya Sin", "Yaa Siin"),
    _surah(37, "الصافات", "As-Saffat", "Those Ranged in Ranks", "As-Saffat", "Saffat", "As Saffat"),
    _surah(38, "ص", "Sad", "The Letter Sad", "Sad", "Shaad"),
    _surah(39, "الزمر", "Az-Zumar", "The Troops", "Az-Zumar", "Zumar", "Az Zumar"),
    _surah(40, "غافر", "Ghafir", "The Forgiver", "Ghafir", "Ghaafir", "Al-Mu'min"),
    _surah(41, "فصلت", "Fussilat", "Explained in Detail", "Fussilat", "Ha Mim"),
    _surah(42, "الشورى", "Ash-Shura", "The Consultation", "Ash-Shura", "Shura", "Asy-Syura"),
    _surah(43, "الزخرف", "Az-Zukhruf", "The Ornaments of Gold", "Az-Zukhruf", "Zukhruf", "Az Zukhruf"),
    _surah(44, "الدخان", "Ad-Dukhan", "The Smoke", "Ad-Dukhan", "Dukhan", "Ad Dukhan"),
    _surah(45, "الجاثية", "Al-Jathiyah", "The Kneeling", "Al-Jathiyah", "Jathiyah", "Al Jathiyah"),
    _surah(46, "الأحقاف", "Al-Ahqaf", "The Wind-Curved Sandhills", "Al-Ahqaf", "Ahqaf", "Al Ahqaf"),
    _surah(47, "محمد", "Muhammad", "Muhammad", "Muhammad"),
    _surah(48, "الفتح", "Al-Fath", "The Victory", "Al-Fath", "Fath", "Al Fath"),
    _surah(49, "الحجرات", "Al-Hujurat", "The Rooms", "Al-Hujurat", "Hujurat", "Al Hujurat"),
    _surah(50, "ق", "Qaf", "The Letter Qaf", "Qaf", "Qaaf"),
    _surah(51, "الذاريات", "Adh-Dhariyat", "The Winnowing Winds", "Adh-Dhariyat", "Dhariyat", "Az-Zariyat"),
    _surah(52, "الطور", "At-Tur", "The Mount", "At-Tur", "Tur", "At Tur"),
    _surah(53, "النجم", "An-Najm", "The Star", "An-Najm", "Najm", "An Najm"),
    _surah(54, "القمر", "Al-Qamar", "The Moon", "Al-Qamar", "Qamar", "Al Qamar"),
    _surah(55, "الرحمن", "Ar-Rahman", "The Most Merciful", "Ar-Rahman", "Rahman", "Ar Rahman"),
    _surah(56, "الواقعة", "Al-Waqi'ah", "The Inevitable", "Al-Waqi'ah", "Waqiah", "Al Waqiah"),
    _surah(57, "الحديد", "Al-Hadid", "The Iron", "Al-Hadid", "Hadid", "Al Hadid"),
    _surah(58, "المجادلة", "Al-Mujadila", "The Pleading Woman", "Al-Mujadilah", "Mujadilah", "Al-Mujadila"),
    _surah(59, "الحشر", "Al-Hashr", "The Exile", "Al-Hashr", "Hashr", "Al Hashr"),
    _surah(60, "الممتحنة", "Al-Mumtahanah", "She That Is Tested", "Al-Mumtahanah", "Mumtahanah"),
    _surah(61, "الصف", "As-Saff", "The Ranks", "As-Saff", "Saff", "As Saff"),
    _surah(62, "الجمعة", "Al-Jumu'ah", "The Congregation, Friday", "Al-Jumuah", "Jumuah", "Al Jumu'ah", "Jumaat"),
    _surah(63, "المنافقون", "Al-Munafiqun", "The Hypocrites", "Al-Munafiqun", "Munafiqun", "Al Munafiqun"),
    _surah(64, "التغابن", "At-Taghabun", "The Mutual Disillusion", "At-Taghabun", "Taghabun", "At Taghabun"),
    _surah(65, "الطلاق", "At-Talaq", "The Divorce", "At-Talaq", "Talaq", "At Talaq"),
    _surah(66, "التحريم", "At-Tahrim", "The Prohibition", "At-Tahrim", "Tahrim", "At Tahrim"),
    _surah(67, "الملك", "Al-Mulk", "The Sovereignty", "Al-Mulk", "Mulk", "Al Mulk"),
    _surah(68, "القلم", "Al-Qalam", "The Pen", "Al-Qalam", "Qalam", "Al Qalam"),
    _surah(69, "الحاقة", "Al-Haqqah", "The Reality", "Al-Haqqah", "Haqqah", "Al Haqqah"),
    _surah(70, "المعارج", "Al-Ma'arij", "The Ascending Stairways", "Al-Maarij", "Maarij", "Al Ma'arij"),
    _surah(71, "نوح", "Nuh", "Noah", "Nuh"),
    _surah(72, "الجن", "Al-Jinn", "The Jinn", "Al-Jinn", "Jinn", "Al Jinn"),
    _surah(73, "المزمل", "Al-Muzzammil", "The Enshrouded One", "Al-Muzzammil", "Muzzammil", "Al Muzzammil"),
    _surah(74, "المدثر", "Al-Muddaththir", "The Cloaked One", "Al-Muddaththir", "Muddathir", "Al Muddaththir"),
    _surah(75, "القيامة", "Al-Qiyamah", "The Resurrection", "Al-Qiyamah", "Qiyamah", "Al Qiyamah"),
    _surah(76, "الإنسان", "Al-Insan", "The Man", "Al-Insan", "Insan", "Al Insan"),
    _surah(77, "المرسلات", "Al-Mursalat", "The Emissaries", "Al-Mursalat", "Mursalat", "Al Mursalat"),
    _surah(78, "النبأ", "An-Naba", "The Tidings", "An-Naba", "Naba", "An Naba"),
    _surah(79, "النازعات", "An-Nazi'at", "Those Who Drag Forth", "An-Naziat", "Naziat", "An Nazi'at"),
    _surah(80, "عبس", "Abasa", "He Frowned", "Abasa", "Abasa"),
    _surah(81, "التكوير", "At-Takwir", "The Overthrowing", "At-Takwir", "Takwir", "At Takwir"),
    _surah(82, "الانفطار", "Al-Infitar", "The Cleaving", "Al-Infitar", "Infitar", "Al Infitar"),
    _surah(83, "المطففين", "Al-Mutaffifin", "The Defrauding", "Al-Mutaffifin", "Mutaffifin", "Al Mutaffifin"),
    _surah(84, "الانشقاق", "Al-Inshiqaq", "The Sundering", "Al-Inshiqaq", "Inshiqaq", "Al Inshiqaq"),
    _surah(85, "البروج", "Al-Buruj", "The Constellations", "Al-Buruj", "Buruj", "Al Buruj"),
    _surah(86, "الطارق", "At-Tariq", "The Nightcomer", "At-Tariq", "Tariq", "At Tariq"),
    _surah(87, "الأعلى", "Al-A'la", "The Most High", "Al-A'la", "Al-Ala", "Al A'la", "Al A'laa"),
    _surah(88, "الغاشية", "Al-Ghashiyah", "The Overwhelming", "Al-Ghashiyah", "Ghashiyah", "Al Ghashiyah"),
    _surah(89, "الفجر", "Al-Fajr", "The Dawn", "Al-Fajr", "Fajr", "Al Fajr"),
    _surah(90, "البلد", "Al-Balad", "The City", "Al-Balad", "Balad", "Al Balad"),
    _surah(91, "الشمس", "Ash-Shams", "The Sun", "Ash-Shams", "Shams", "Asy-Syams"),
    _surah(92, "الليل", "Al-Layl", "The Night", "Al-Layl", "Lail", "Layl", "Al Lail"),
    _surah(93, "الضحى", "Ad-Duha", "The Morning Hours", "Ad-Duha", "Duha", "Ad Duha"),
    _surah(94, "الشرح", "Ash-Sharh", "The Relief", "Ash-Sharh", "Sharh", "Asy-Syarh", "Al-Inshirah"),
    _surah(95, "التين", "At-Tin", "The Fig", "At-Tin", "Tin", "At Tin"),
    _surah(96, "العلق", "Al-'Alaq", "The Clot", "Al-Alaq", "Alaq", "Al 'Alaq"),
    _surah(97, "القدر", "Al-Qadr", "The Power", "Al-Qadr", "Qadr", "Al Qadr"),
    _surah(98, "البينة", "Al-Bayyinah", "The Clear Proof", "Al-Bayyinah", "Bayyinah", "Al Bayyinah"),
    _surah(99, "الزلزلة", "Az-Zalzalah", "The Earthquake", "Az-Zalzalah", "Zalzalah", "Az Zalzalah"),
    _surah(100, "العاديات", "Al-'Adiyat", "The Courser", "Al-Adiyat", "Adiyat", "Al 'Adiyat"),
    _surah(101, "القارعة", "Al-Qari'ah", "The Calamity", "Al-Qariah", "Qariah", "Al Qari'ah"),
    _surah(102, "التكاثر", "At-Takathur", "The Rivalry", "At-Takathur", "Takathur", "At Takathur"),
    _surah(103, "العصر", "Al-'Asr", "The Declining Day, Time", "Al-Asr", "Asr", "Al 'Asr"),
    _surah(104, "الهمزة", "Al-Humazah", "The Traducer", "Al-Humazah", "Humazah", "Al Humazah"),
    _surah(105, "الفيل", "Al-Fil", "The Elephant", "Al-Fil", "Fil", "Al Fil"),
    _surah(106, "قريش", "Quraysh", "Quraysh", "Quraish", "Quraysh"),
    _surah(107, "الماعون", "Al-Ma'un", "Small Kindnesses", "Al-Ma'un", "Ma'un", "Maaun", "Al Ma'un", "Al-Maun"),
    _surah(108, "الكوثر", "Al-Kawthar", "The Abundance", "Al-Kawthar", "Kausar", "Kawthar", "Al Kausar", "Al-Kautsar"),
    _surah(109, "الكافرون", "Al-Kafirun", "The Disbelievers", "Al-Kafirun", "Kafirun", "Al Kafirun"),
    _surah(110, "النصر", "An-Nasr", "The Divine Support", "An-Nasr", "Nasr", "An Nasr"),
    _surah(111, "المسد", "Al-Masad", "The Palm Fiber", "Al-Masad", "Masad", "Al Lahab", "Abu Lahab"),
    _surah(112, "الإخلاص", "Al-Ikhlas", "The Sincerity", "Al-Ikhlas", "Ikhlas", "Al Ikhlas"),
    _surah(113, "الفلق", "Al-Falaq", "The Daybreak", "Al-Falaq", "Falaq", "Al Falaq"),
    _surah(114, "الناس", "An-Nas", "Mankind", "An-Nas", "Nas", "An Nas"),
)

_BY_NUMBER: dict[int, Surah] = {s.number: s for s in SURAHS}
_ALIAS_LOOKUP: dict[str, Surah] = {}


def _normalize(text: str) -> str:
    """Lowercase and strip diacritics/punctuation for matching."""
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", text)
    without_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
    return "".join(
        c for c in without_diacritics.lower() if c.isalnum()
    )


def _build_lookup() -> None:
    if _ALIAS_LOOKUP:
        return
    for surah in SURAHS:
        _ALIAS_LOOKUP[_normalize(surah.transliteration)] = surah
        _ALIAS_LOOKUP[_normalize(surah.english)] = surah
        for alias in surah.aliases:
            _ALIAS_LOOKUP[_normalize(alias)] = surah


_build_lookup()


def get_surah_by_number(number: int) -> Surah | None:
    return _BY_NUMBER.get(number)


def find_surah(text: str) -> Surah | None:
    """Find the first surah mentioned in ``text``, or None."""
    normalized = _normalize(text)
    if not normalized:
        return None
    best: Surah | None = None
    best_index = len(normalized) + 1
    for alias, surah in _ALIAS_LOOKUP.items():
        idx = normalized.find(alias)
        if idx != -1 and idx < best_index:
            best = surah
            best_index = idx
    return best


def all_surahs() -> tuple[Surah, ...]:
    return SURAHS
