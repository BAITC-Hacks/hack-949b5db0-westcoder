"""Explainable keyword fallback, not a claim to understand arbitrary language."""
import re
from .models import normalized

CONCEPTS = {
    "спокойная подача": ("спокой", "ненавязчив", "деликат"),
    "камерная атмосфера": ("камерн", "лампов", "уютн"),
    "юмор": ("юмор", "шутк"),
    "конкурсы": ("конкурс",),
    "шум": ("шум",),
    "импровизация": ("импровиз",),
    "динамичная подача": ("динамич", "энергич", "драйв"),
    "джаз": ("джаз", "jazz"),
    "классическая музыка": ("классик", "классическ"),
    "ретро": ("ретро",),
    "живая музыка": ("живую музыку", "живой музык", "живая музык"),
    "естественные эмоции": ("естествен", "искренн", "живые эмоц", "живыми эмоц"),
    "репортаж": ("репортаж", "документальн", "фотожурнал"),
    "постановочная съёмка": ("постановоч", "позирован"),
    "минимализм": ("минимал",),
    "традиции": ("традиц", "национальн", "этно"),
    "индивидуальный подход": ("индивидуальн", "персональн",),
    "панорамный вид": ("панорам", "вид на гор",),
    "терраса": ("террас",),
    "скрипка": ("скрип",),
    "саксофон": ("саксофон",),
}
STOP = {"хочу", "нужен", "нужна", "нужно", "ищем", "ищу", "очень", "чтобы", "который", "ведущий", "ведущего", "фотограф", "мероприятие", "свадьба", "свадьбы"}


def mentions(text, roots):
    text = normalized(text)
    found = []
    for clause in re.split(r"[,.;!?\n]|\bно\b", text):
        for root in roots:
            match = re.search(r"\b" + re.escape(root), clause)
            if match:
                prefix = clause[max(0, match.start() - 45):match.start()]
                negated = bool(re.search(r"\b(?:без|не|никаких)\s+(?:[\w-]+\s+){0,2}$", prefix))
                found.append(not negated)
    return found


def assess_preferences(description, preferences):
    if not preferences:
        return {"value": None, "evidence": [], "conflicts": [], "unverified": []}
    requested = []
    covered = normalized(preferences)
    for label, roots in CONCEPTS.items():
        signs = mentions(preferences, roots)
        if signs:
            requested.append((label, roots, signs[-1]))
            for root in roots:
                covered = re.sub(r"\b" + re.escape(root) + r"\w*", "", covered)
    # Unrecognized content words are checked literally, with no invented synonyms.
    for word in dict.fromkeys(re.findall(r"[а-яa-z]{4,}", covered)):
        if word not in STOP:
            requested.append((word, (word,), mentions(preferences, (word,))[-1]))
    evidence, conflicts, unverified = [], [], []
    sentences = re.split(r"(?<=[.!?])\s+|\n", description)
    for label, roots, positive in requested:
        title = label if positive else "без: " + label
        signs = mentions(description, roots)
        if signs and positive in signs and (not positive) not in signs:
            sentence = next((s for s in sentences if positive in mentions(s, roots)), description)
            # A verbatim excerpt is evidence for the word, not an inferred quality.
            evidence.append({"label": title, "excerpt": sentence[:500]})
        elif signs and (not positive) in signs:
            conflicts.append(title)
        else:
            unverified.append(title)
    value = len(evidence) / len(requested) if requested else 0.0
    return {"value": value, "evidence": evidence, "conflicts": conflicts, "unverified": unverified}
