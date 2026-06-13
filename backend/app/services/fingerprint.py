"""MinHash body fingerprints for near-duplicate detection.

A normalized body is shingled into overlapping word k-grams; a fixed family of
hash permutations turns the shingle set into a compact signature whose
element-wise agreement estimates the Jaccard overlap of two bodies. Splitting
the signature into bands yields LSH block keys: two bodies share a band key
only when a run of their signatures matches, so high-overlap pairs collide (and
get scored) while the candidate set stays well short of O(n^2).

This complements the exact ``body:`` / ``body_prefix:`` block keys: it recovers
near-duplicates that differ by an added footer, a trailing quote, or light
edits -- cases an exact hash or a fixed-prefix hash both miss.

Pure standard library; no third-party dependency. Signatures are deterministic
across processes (fixed permutation seed) so persisted values stay comparable.
"""

import hashlib
import random
from collections import namedtuple
from typing import List, Optional, Sequence

SHINGLE_WORDS = 5  # words per shingle (k-gram)
SIGNATURE_SIZE = 64  # number of MinHash permutations
LSH_BANDS = 16  # LSH_BANDS * LSH_ROWS must equal SIGNATURE_SIZE
LSH_ROWS = SIGNATURE_SIZE // LSH_BANDS
# Bodies shorter than this (normalized chars) are not fingerprinted: too little
# text to shingle meaningfully, and the exact body/prefix block keys already
# cover them. Sits just below the 160-char body_prefix threshold.
MIN_FINGERPRINT_LEN = 120

_MERSENNE_PRIME = (1 << 61) - 1
_HASH_CEILING = 1 << 32

# Fixed permutation coefficients (a, b) for a universal hash family. The fixed
# seed keeps signatures stable across runs so persisted ones remain comparable.
_rng = random.Random(0xE3A1C0DE)
_COEFFS = [
    (_rng.randrange(1, _MERSENNE_PRIME), _rng.randrange(0, _MERSENNE_PRIME))
    for _ in range(SIGNATURE_SIZE)
]

# normalized: the canonical body the signature was computed from (reused for the
# exact body/prefix block keys). signature: the MinHash, or None when the body
# is too short to fingerprint. hashes: the set of shingle hashes the signature
# (and containment) are derived from -- computed once per email and reused so
# per-pair containment is a cheap set intersection, not a re-shingle.
Fingerprint = namedtuple("Fingerprint", ("normalized", "signature", "hashes"))


def shingles(normalized_body: str, k: int = SHINGLE_WORDS) -> List[str]:
    """Overlapping k-word shingles of an already-normalized body."""
    words = normalized_body.split()
    if len(words) < k:
        return [normalized_body] if normalized_body else []
    return [" ".join(words[i : i + k]) for i in range(len(words) - k + 1)]


def _base_hash(shingle: str) -> int:
    return int.from_bytes(hashlib.blake2b(shingle.encode("utf-8"), digest_size=4).digest(), "big")


def shingle_hashes(normalized_body: str) -> set:
    """Set of shingle hashes for a body -- the shared input to MinHash and
    containment, so a body is shingled at most once per recompute."""
    return {_base_hash(s) for s in shingles(normalized_body)}


def minhash_from_hashes(base: set) -> Optional[List[int]]:
    """MinHash signature from a precomputed shingle-hash set."""
    if not base:
        return None
    return [min(((a * x + b) % _MERSENNE_PRIME) % _HASH_CEILING for x in base) for a, b in _COEFFS]


def minhash(normalized_body: str) -> Optional[List[int]]:
    """MinHash signature of a normalized body, or None if it is too short."""
    if len(normalized_body) < MIN_FINGERPRINT_LEN:
        return None
    return minhash_from_hashes(shingle_hashes(normalized_body))


def compute_fingerprint(normalized_body: str) -> Fingerprint:
    base = shingle_hashes(normalized_body)
    signature = minhash_from_hashes(base) if len(normalized_body) >= MIN_FINGERPRINT_LEN else None
    return Fingerprint(normalized_body, signature, base)


def minhash_jaccard(left: Optional[Sequence[int]], right: Optional[Sequence[int]]) -> float:
    """Estimated Jaccard overlap (0..1) from two signatures of equal length."""
    if not left or not right or len(left) != len(right):
        return 0.0
    matches = sum(1 for x, y in zip(left, right) if x == y)
    return matches / len(left)


# Minimum shingles the smaller body needs before its containment ratio is
# trusted; below this a short, generic block could be "contained" by chance.
MIN_CONTAINMENT_SHINGLES = 5


def containment_from_hashes(left: set, right: set) -> float:
    """Fraction of the smaller shingle-hash set also present in the larger one.

    Catches one email embedded in another -- a forward, or a reply that quotes
    the original -- where the symmetric Jaccard is low because the union is
    large. Returns 0.0 when the smaller body has too few shingles to judge.
    """
    if not left or not right:
        return 0.0
    small, large = (left, right) if len(left) <= len(right) else (right, left)
    if len(small) < MIN_CONTAINMENT_SHINGLES:
        return 0.0
    return len(small & large) / len(small)


def body_containment(left_norm: str, right_norm: str) -> float:
    """Containment of two normalized bodies, shingling on the fly. Hot paths
    pass precomputed sets to ``containment_from_hashes`` instead."""
    return containment_from_hashes(shingle_hashes(left_norm), shingle_hashes(right_norm))


def lsh_band_keys(signature: Optional[Sequence[int]]) -> List[str]:
    """LSH band block keys for a signature (empty when there is no signature)."""
    if not signature:
        return []
    keys = []
    for band in range(LSH_BANDS):
        chunk = tuple(signature[band * LSH_ROWS : (band + 1) * LSH_ROWS])
        digest = hashlib.blake2b(repr(chunk).encode("utf-8"), digest_size=8).hexdigest()
        keys.append(f"lsh:{band}:{digest}")
    return keys
