"""
Summarization module.

Dependency-free extractive summarizer: it scores each sentence by the
frequency of the meaningful words it contains, then returns the highest
scoring sentences in their original order so the summary still reads
in sequence.
"""

import re
from collections import Counter

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "did", "do", "does", "doing", "down",
    "during", "each", "few", "for", "from", "further", "had", "has", "have",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me",
    "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on",
    "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over",
    "own", "s", "said", "same", "she", "should", "so", "some", "such", "t",
    "than", "that", "the", "their", "theirs", "them", "themselves", "then",
    "there", "these", "they", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "would", "you", "your",
    "yours", "yourself", "yourselves",
}

# Split on sentence-ending punctuation followed by whitespace and a capital
# letter / digit / quote, so decimals and common abbreviations survive.
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+(?=["\'(]?[A-Z0-9])')
_WORD = re.compile(r"[a-z][a-z'-]+")


def split_sentences(text):
    """Break text into clean sentences."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    parts = _SENTENCE_SPLIT.split(text)
    return [p.strip() for p in parts if len(p.strip()) > 1]


def summarize(text, max_sentences=4):
    """
    Return an extractive summary of `text` with at most `max_sentences`
    sentences, keeping their original order.
    """
    sentences = split_sentences(text)
    if not sentences:
        return ""
    if len(sentences) <= max_sentences:
        return " ".join(sentences)

    # Word frequencies, ignoring stopwords.
    freqs = Counter(
        w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 2
    )
    if not freqs:
        return " ".join(sentences[:max_sentences])

    top = freqs.most_common(1)[0][1]

    scored = []
    for index, sentence in enumerate(sentences):
        words = [
            w for w in _WORD.findall(sentence.lower())
            if w not in STOPWORDS and len(w) > 2
        ]
        if not words:
            scored.append((index, 0.0))
            continue
        # Normalised score, averaged over length so long sentences don't
        # automatically win.
        score = sum(freqs[w] / top for w in words) / (len(words) ** 0.5)
        # Mild bias toward the opening of an article, where news writing
        # puts the main point.
        if index < 3:
            score *= 1.15
        scored.append((index, score))

    best = sorted(scored, key=lambda pair: pair[1], reverse=True)[:max_sentences]
    chosen = sorted(idx for idx, _ in best)
    return " ".join(sentences[i] for i in chosen)
