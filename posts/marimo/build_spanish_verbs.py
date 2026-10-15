"""Build spanish_verbs.json for the conjugation tool in exploring-marimo-quarto.qmd.

Run once, offline. The inputs are large, so download them outside the repo:

  Spanish (English Wiktionary, via Kaikki/wiktextract, ~1 GB):
    https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl
  Latin (same source, ~1.2 GB), used for the cognate trees:
    https://kaikki.org/dictionary/Latin/kaikki.org-dictionary-Latin.jsonl
  Word frequencies (OpenSubtitles 2018, Hermit Dave's FrequencyWords):
    https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/es/es_50k.txt

Usage:
  python build_spanish_verbs.py SPANISH_JSONL LATIN_JSONL FREQ_TXT [--top 1000] [--out spanish_verbs.json]

Ranking. The frequency list counts word forms, not verbs, so each verb is scored
from the counts of its conjugated forms:

  - A form that is also a non-verb word (como, para, casa, claro) is left out,
    because subtitle counts can't separate the verbal use.
  - A form only one verb produces counts in full.
  - A form several verbs share (fue: ser and ir; creo: creer and crear) is split
    in proportion to each verb's score from its unshared forms.

Only entries whose headword is an infinitive are kept, so pronominal and clitic
entries (llamarse, arreglárselas) fall to their base verb. Entries whose senses
are all alternative forms, misspellings, or rare/obsolete are skipped.
"""

import argparse
import json
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

PERSONS = {
    "yo": "yo",
    "tu": "tú",
    "vos": "vos",
    "el": "él/ella/usted",
    "nosotros": "nosotros/as",
    "vosotros": "vosotros/as",
    "ellos": "ellos/ellas/ustedes",
}

TENSES = {
    "present": ("Present", "Presente"),
    "preterite": ("Preterite", "Pretérito perfecto simple"),
    "imperfect": ("Imperfect", "Pretérito imperfecto"),
    "future": ("Future", "Futuro"),
    "conditional": ("Conditional", "Condicional"),
    "present_subjunctive": ("Present subjunctive", "Presente de subjuntivo"),
    "imperfect_subjunctive": ("Imperfect subjunctive", "Pretérito imperfecto de subjuntivo"),
    "imperative": ("Imperative", "Imperativo afirmativo"),
    "imperative_negative": ("Negative imperative", "Imperativo negativo"),
}

# Parts of speech that don't make a verb form ambiguous. Proper names do: the
# frequency list is lowercased subtitles, where "orlando" and "ada" are names,
# not forms of orlar and adir.
IGNORE_POS = {"verb", "character", "symbol", "punct", "suffix", "prefix",
              "infix", "interfix", "proverb", "phrase", "prep_phrase", "adv_phrase"}
SKIP_SENSE_TAGS = {"obsolete", "archaic", "rare", "misspelling", "alt-of"}

# Older per-relation templates: {{inh|es|la|fabulor|fābulārī}}.
ANCESTOR_TEMPLATES = {
    "inh": "inherited", "inh+": "inherited",
    "der": "derived", "der+": "derived",
    "bor": "borrowed", "bor+": "borrowed", "obor": "borrowed", "ubor": "borrowed",
    "lbor": "learned borrowing", "lbor+": "learned borrowing", "slbor": "learned borrowing",
}
AFFIX_TEMPLATES = {"af", "affix", "prefix", "suffix", "confix", "compound", "surf"}

# Newer {{ety}}/{{etymon}} templates: alternating ":keyword" and
# "lang:term<modifiers>" arguments, where an <ety:...> modifier nests the
# term's own etymology, e.g. osp:estar<ety:inh<la:stō<alt:stō, stare>>>.
ETY_RELATIONS = {
    "inh": "inherited", "der": "derived", "uder": "derived", "from": "derived",
    "bor": "borrowed", "obor": "borrowed", "ubor": "borrowed",
    "lbor": "learned borrowing", "slbor": "learned borrowing", "calque": "calque",
}

# Abbreviations the flattened etymology tree glues onto a node's word.
TREE_SUFFIXES = ("influ.", "lbor.", "bor.", "der.", "inh.", "calq.")

# Languages kept in the cognate trees. Intermediate stages (Old Spanish, Old
# French) are kept when they lead to one of these.
COGNATE_LANGS = {"es", "pt", "gl", "ca", "fr", "it", "ro", "en"}


def strip_marks(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tense_key(tags):
    if tags & {"combined-form", "imperfect-se", "error-unrecognized-form"}:
        return None
    if "imperative" in tags:
        return "imperative_negative" if "negative" in tags else "imperative"
    if "subjunctive" in tags:
        if "present" in tags:
            return "present_subjunctive"
        if "imperfect" in tags:
            return "imperfect_subjunctive"
        return None
    if "indicative" in tags:
        for t in ("present", "preterite", "imperfect", "future", "conditional"):
            if t in tags:
                return t
    return None


def person_key(tags):
    if "singular" in tags:
        if "first-person" in tags:
            return "yo"
        if "second-person" in tags:
            return "vos" if "vos-form" in tags else "tu"
        if "third-person" in tags:
            return "el"
    elif "plural" in tags:
        if "first-person" in tags:
            return "nosotros"
        if "second-person" in tags:
            return "vosotros"
        if "third-person" in tags:
            return "ellos"
    return None


def etymology_tree_lines(text, word):
    """The {{ety}} tree, flattened by wiktextract into "Language word" lines that
    run from the oldest ancestor down to the entry itself."""
    if not text.startswith("Etymology tree"):
        return [], text.strip()
    marker = f"\nSpanish {word}\n"
    cut = text.find(marker)
    if cut == -1:
        return [], ""
    return text[len("Etymology tree\n"):cut].split("\n"), text[cut + len(marker):].strip()


def latin_from_tree(lines):
    for line in reversed(lines):
        if line.startswith("Latin "):
            display = line[len("Latin "):]
            for suffix in TREE_SUFFIXES:
                display = display.removesuffix(suffix)
            return {"relation": "from", "lang": "Latin", "code": "la", "word": display,
                    "lemma": display.split(", ")[0], "gloss": None}
    return None


def ancestor_from_template(t):
    args = t.get("args", {})
    code, lemma = args.get("2", ""), args.get("3", "")
    display = args.get("4") or lemma
    if not code or not display:
        return None
    expansion = t.get("expansion", "")
    if t["name"].endswith("+") and " from " in expansion:
        expansion = expansion.split(" from ", 1)[1]
    idx = expansion.find(display)
    lang = expansion[:idx].strip() if idx > 0 else code
    return {
        "relation": ANCESTOR_TEMPLATES[t["name"]],
        "lang": lang,
        "code": code,
        "word": display,
        "lemma": lemma or display,
        "gloss": args.get("5") or args.get("t") or args.get("gloss") or None,
    }


def split_modifiers(term):
    """'la:stō<alt:stō, stare><t:to stand>' -> ('la:stō', ['alt:stō, stare', 't:to stand'])"""
    start = term.find("<")
    if start == -1:
        return term, []
    mods, depth, buf = [], 0, ""
    for ch in term[start:]:
        if ch == "<":
            depth += 1
            if depth == 1:
                buf = ""
                continue
        elif ch == ">":
            depth -= 1
            if depth == 0:
                mods.append(buf)
                continue
        buf += ch
    return term[:start], mods


def parse_ety_term(term, relation, default_lang):
    head, mods = split_modifiers(term)
    code, _, lemma = head.rpartition(":")
    a = {"relation": relation, "lang": None, "code": code or default_lang,
         "word": lemma, "lemma": lemma, "gloss": None}
    chain = [a]
    for m in mods:
        key, _, val = m.partition(":")
        if key == "alt":
            a["word"] = val
        elif key in ("t", "gloss"):
            a["gloss"] = val
        elif key == "ety":
            keyword, nested = split_modifiers(val)
            if keyword in ETY_RELATIONS:
                for n in nested:
                    chain += parse_ety_term(n, ETY_RELATIONS[keyword], a["code"])
    return chain


def parse_ety_args(args):
    ancestors, parts, relation = [], [], None
    for k in sorted((k for k in args if k.isdigit() and k != "1"), key=int):
        v = args[k]
        if v.startswith(":"):
            relation = v[1:]
        elif relation in ETY_RELATIONS:
            ancestors += parse_ety_term(v, ETY_RELATIONS[relation], args.get("1", "es"))
        elif relation in AFFIX_TEMPLATES:
            parts.append(split_modifiers(v)[0].rpartition(":")[2])
    return ancestors, parts


def read_spanish(path):
    lemmas = {}
    non_verb_words = set()
    lang_names = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            pos, word = e.get("pos"), e.get("word", "")
            for t in e.get("etymology_templates", []):
                if t.get("name") in ANCESTOR_TEMPLATES and (a := ancestor_from_template(t)) and a["lang"] != a["code"]:
                    lang_names.setdefault(a["code"], a["lang"])
            if pos not in IGNORE_POS:
                non_verb_words.add(word.lower())
                continue
            if pos != "verb" or " " in word or not word.endswith("r"):
                continue
            forms = e.get("forms", [])
            if not any(fm.get("source") == "conjugation" for fm in forms):
                continue
            senses = [s for s in e.get("senses", []) if "form_of" not in s and "alt_of" not in s]
            if all(SKIP_SENSE_TAGS & set(s.get("tags", [])) for s in senses):
                continue
            lemmas.setdefault(word, []).append(e)
    return lemmas, non_verb_words, lang_names


def build_verb(word, entries, lang_names):
    conj_entry = next(e for e in entries if any(fm.get("source") == "conjugation" for fm in e["forms"]))
    conjugations = {k: {} for k in TENSES}
    gerund = participle = None
    irregular = False
    for fm in conj_entry["forms"]:
        if fm.get("source") != "conjugation":
            continue
        tags = set(fm.get("tags", []))
        if "table-tags" in tags:
            irregular = fm["form"] == "irregular"
            continue
        if tags == {"gerund"}:
            gerund = gerund or fm["form"]
        elif tags == {"masculine", "participle", "past", "singular"}:
            participle = participle or fm["form"]
        tense, person = tense_key(tags), person_key(tags)
        if tense and person:
            conjugations[tense].setdefault(person, fm["form"])
    # Wiktionary gives a separate vos form only where it differs from tú.
    for slots in conjugations.values():
        if "tu" in slots:
            slots.setdefault("vos", slots["tu"])

    glosses, texts, ancestors, parts, tree_lines = [], [], [], [], []
    for e in entries:
        for s in e.get("senses", []):
            g = (s.get("glosses") or [None])[0]
            if g and g not in glosses and "form_of" not in s and "alt_of" not in s:
                glosses.append(g)
        lines, text = etymology_tree_lines(e.get("etymology_text", ""), word)
        tree_lines += lines
        if text and text not in texts:
            texts.append(text)
        for t in e.get("etymology_templates", []):
            name, args = t.get("name"), t.get("args", {})
            if name in ANCESTOR_TEMPLATES:
                if a := ancestor_from_template(t):
                    ancestors.append(a)
            elif name in ("ety", "etymon"):
                anc, p = parse_ety_args(args)
                ancestors += anc
                parts = parts or p
            elif name in AFFIX_TEMPLATES and not parts:
                parts = [args[k] for k in sorted((k for k in args if k.isdigit() and k != "1"), key=int) if args[k]]

    if not any(a["code"] == "la" for a in ancestors) and (a := latin_from_tree(tree_lines)):
        ancestors.append(a)
    # A reconstructed form can be cited twice, under a broad and a specific
    # language code (la and la-vul for *sedentāre). It can't be attested Latin,
    # so keep one copy with the specific code.
    unique, seen = [], {}
    for a in ancestors:
        a["lang"] = lang_names.get(a["code"], a["lang"] or a["code"])
        key = (a["code"], strip_marks(a["lemma"]))
        prev = seen.get(strip_marks(a["word"])) if a["word"].startswith("*") else None
        if key in seen:
            continue
        if prev is not None:
            if a["code"].startswith(prev["code"] + "-"):
                prev["code"], prev["lang"] = a["code"], a["lang"]
            continue
        seen[key] = a
        seen[strip_marks(a["word"])] = a
        unique.append(a)

    ipa = next((s["ipa"] for e in entries for s in e.get("sounds", []) if "ipa" in s), None)
    return {
        "infinitive": word,
        "glosses": glosses[:3],
        "ipa": ipa,
        "irregular": irregular,
        "gerund": gerund,
        "past_participle": participle,
        "conjugations": conjugations,
        "etymology_text": "\n\n".join(texts) or None,
        "ancestors": unique,
        "parts": parts,
        "cognates": None,
    }


def all_forms(entries):
    forms = set()
    for e in entries:
        for fm in e.get("forms", []):
            tags = set(fm.get("tags", []))
            if fm.get("source") == "conjugation" and not tags & {"table-tags", "inflection-template"}:
                form = fm["form"].lower()
                if " " not in form:
                    forms.add(form)
    return forms


def rank_verbs(lemmas, non_verb_words, freq):
    forms_by_verb = {w: all_forms(es) - non_verb_words for w, es in lemmas.items()}
    claimants = defaultdict(list)
    for word, forms in forms_by_verb.items():
        for form in forms:
            claimants[form].append(word)
    base = {
        word: sum(freq.get(form, 0) for form in forms if len(claimants[form]) == 1)
        for word, forms in forms_by_verb.items()
    }
    scores = dict(base)
    for form, verbs in claimants.items():
        if len(verbs) < 2 or form not in freq:
            continue
        total = sum(base[v] for v in verbs)
        for v in verbs:
            scores[v] += freq[form] * (base[v] / total if total else 1 / len(verbs))
    return sorted(scores, key=lambda w: (-scores[w], w)), scores


def is_latin_script(word):
    # Drops the Moldovan Cyrillic spellings listed alongside Romanian.
    return all(not c.isalpha() or unicodedata.name(c, "").startswith("LATIN") for c in word)


def contains(nodes, code, word):
    return any(
        (n.get("lang_code") == code and n.get("word") == word) or contains(n.get("descendants", []), code, word)
        for n in nodes
    )


def prune(nodes, seen):
    out = []
    for n in nodes:
        children = prune(n.get("descendants", []), seen)
        code, word = n.get("lang_code"), n.get("word")
        keep_self = code in COGNATE_LANGS and word and is_latin_script(word) and (code, word) not in seen
        if keep_self:
            seen.add((code, word))
        if not (keep_self or children):
            continue
        node = {"lang": n.get("lang"), "code": code, "word": word}
        if "borrowed" in n.get("raw_tags", []):
            node["borrowed"] = True
        if children:
            node["children"] = children
        out.append(node)
    return out


def read_latin(path, keys):
    """Latin entries with descendants, indexed by headword and by infinitive,
    since Spanish etymologies cite either (fabulor, dormīre)."""
    found = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if not e.get("descendants"):
                continue
            names = {e.get("word", "")} | {
                fm["form"] for fm in e.get("forms", []) if "infinitive" in fm.get("tags", [])
            }
            for key in {strip_marks(n) for n in names} & keys:
                found[key].append(e)
    return found


def attach_cognates(verbs, latin_path):
    def latin_ancestors(v):
        # Reconstructed forms (*sedentāre) have no Latin entry to look up.
        return [a for a in v["ancestors"] if a["code"] == "la" and not a["lemma"].startswith("*")]

    keys = {strip_marks(a["lemma"]) for v in verbs for a in latin_ancestors(v)}
    latin = read_latin(latin_path, keys)
    for v in verbs:
        for a in latin_ancestors(v):
            candidates = sorted(latin.get(strip_marks(a["lemma"]), []), key=lambda e: e.get("pos") != "verb")
            entry = next((e for e in candidates if contains(e["descendants"], "es", v["infinitive"])), None)
            if entry:
                v["cognates"] = {
                    "lang": "Latin",
                    "code": "la",
                    "word": a["word"],
                    "children": prune(entry["descendants"], set()),
                }
                break


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spanish")
    parser.add_argument("latin")
    parser.add_argument("freq")
    parser.add_argument("--top", type=int, default=1000)
    parser.add_argument("--out", default=str(Path(__file__).with_name("spanish_verbs.json")))
    args = parser.parse_args()

    freq = {}
    with open(args.freq, encoding="utf-8") as f:
        for line in f:
            w, n = line.split()
            freq[w] = int(n)

    lemmas, non_verb_words, lang_names = read_spanish(args.spanish)
    order, scores = rank_verbs(lemmas, non_verb_words, freq)
    verbs = []
    for rank, word in enumerate(order[: args.top], start=1):
        v = build_verb(word, lemmas[word], lang_names)
        verbs.append({"rank": rank, "score": round(scores[word]), **v})
    attach_cognates(verbs, args.latin)

    out = {
        "meta": {
            "generated": date.today().isoformat(),
            "persons": PERSONS,
            "tenses": {k: {"en": en, "es": es} for k, (en, es) in TENSES.items()},
            "ranking": "Sum of OpenSubtitles 2018 counts over each verb's conjugated forms. Forms that are "
                       "also non-verb words are excluded; forms shared between verbs are split in proportion "
                       "to each verb's unshared-form count.",
            "sources": [
                {"name": "Wiktionary (English edition), extracted by Kaikki.org / wiktextract",
                 "url": "https://kaikki.org/", "licence": "CC BY-SA 4.0"},
                {"name": "FrequencyWords (OpenSubtitles 2018), Hermit Dave",
                 "url": "https://github.com/hermitdave/FrequencyWords", "licence": "CC BY-SA 4.0"},
            ],
        },
        "verbs": verbs,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(verbs)} verbs to {args.out}")


if __name__ == "__main__":
    main()
