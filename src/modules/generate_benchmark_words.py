import argparse
import csv
import random
from pathlib import Path
from typing import List

from modules.CYK import cyk_accepts
from domain.grammar_types import Grammar
from modules.parser import parse_grammar_file_to_chomsky


def generate_words_from_grammar(
    grammar: Grammar,
    min_length: int,
    count: int,
    max_length: int | None = None,
    negative: bool = False,
    seed: int | None = None,
    max_tries: int = 20000,
) -> list[str]:
    """
    Generate words from a grammar object.
    - negative=False: generated words are in the language.
    - negative=True: generated words are not in the language.
    Words are tokenized by spaces.
    """
    if min_length < 0:
        raise ValueError("min_length must be non-negative.")
    if count < 0:
        raise ValueError("count must be non-negative.")
    if max_length is not None and max_length < min_length:
        raise ValueError("max_length must be greater than or equal to min_length.")

    terminals = [terminal.value for terminal in grammar.Terminals]
    if not terminals:
        raise ValueError("Cannot generate words: terminal list is empty.")
    if count == 0:
        return []

    rng = random.Random(seed)
    words: list[str] = []
    seen: set[str] = set()
    tries = 0

    # Optional epsilon candidate when minimum length allows it.
    if min_length == 0:
        is_accepted = cyk_accepts(grammar, [])
        if (not negative and is_accepted) or (negative and not is_accepted):
            words.append("")
            seen.add("")
            if len(words) >= count:
                return words

    upper_bound = min_length + 8 if max_length is None else max_length

    while len(words) < count and tries < max_tries:
        tries += 1

        length = rng.randint(min_length, upper_bound)
        tokens = [] if length == 0 else [rng.choice(terminals) for _ in range(length)]
        word = " ".join(tokens)

        if word in seen:
            continue

        accepted = cyk_accepts(grammar, tokens)
        should_take = accepted if not negative else (not accepted)
        if should_take:
            seen.add(word)
            words.append(word)

    if len(words) < count:
        kind = "negative" if negative else "positive"
        raise ValueError(
            f"Could not generate {count} {kind} words for grammar after {max_tries} attempts. "
            f"Generated only {len(words)} words."
        )

    return words

def generate_benchmark_words(
    grammar_file: str,
    min_length: int,
    count: int,
    negative: bool = False,
    output_csv: str | None = None,
    seed: int | None = None,
) -> str:
    """
    Generate benchmarking words for each grammar in a grammar file.
    Each generated word is tokenized with spaces.
    """
    grammars = parse_grammar_file_to_chomsky(grammar_file)
    source_path = Path(grammar_file)

    if output_csv is None:
        output_dir = source_path.parent / "results" / source_path.stem
        output_path = output_dir / f"{source_path.stem}_benchmark_words.csv"
    else:
        output_path = Path(output_csv)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    for idx, grammar in enumerate(grammars, start=1):
        generated = generate_words_from_grammar(
            grammar=grammar,
            min_length=min_length,
            max_length=min_length + 8,
            count=count,
            negative=negative,
            seed=seed,
        )

        for word_idx, word in enumerate(generated, start=1):
            rows.append(
                {
                    "grammar_index": str(idx),
                    "word_index": str(word_idx),
                    "length": str(0 if word == "" else len(word.split())),
                    "negative": str(negative),
                    "word": word,
                }
            )

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["grammar_index", "word_index", "length", "negative", "word"])
        writer.writeheader()
        writer.writerows(rows)

    return str(output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate benchmark words validated against grammar membership.")
    parser.add_argument("grammar_file", help="Path to grammar file (single or multi-grammar).")
    parser.add_argument(
        "--min-length",
        type=int,
        required=True,
        help="Minimal word length in tokens.",
    )
    parser.add_argument(
        "--count",
        type=int,
        required=True,
        help="Number of words to generate per grammar.",
    )
    parser.add_argument(
        "--negative",
        action="store_true",
        help="Generate words that are NOT in the grammar language.",
    )
    parser.add_argument("--output", default=None, help="Output CSV path.")
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed.")

    args = parser.parse_args()

    output = generate_benchmark_words(
        grammar_file=args.grammar_file,
        min_length=args.min_length,
        count=args.count,
        negative=args.negative,
        output_csv=args.output,
        seed=args.seed,
    )
    print(f"Generated benchmark words CSV: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
