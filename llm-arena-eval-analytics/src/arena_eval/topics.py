"""Prompt topic clustering and per-topic leaderboards.

Default backend: TF-IDF -> LSA (TruncatedSVD) -> KMeans. The LSA step matters: raw
TF-IDF clusters split on surface phrasing, while a low-rank projection groups words that
co-occur (on the simulator, adjusted Rand index vs true topics rises from ~0.2 to ~0.9).
Optional backend: sentence-transformer embeddings + KMeans, which gives more
semantic clusters on real prompts (``pip install sentence-transformers``).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import Normalizer

from .ratings import fit_bradley_terry


def cluster_prompts(
    prompts: pd.Series, k: int = 8, backend: str = "tfidf", seed: int = 0,
    svd_components: int = 20,
) -> tuple[np.ndarray, dict[int, str]]:
    """Assign each prompt to a cluster; return labels and a readable name per cluster."""
    text = prompts.fillna("").str.slice(0, 2000)
    tfidf = TfidfVectorizer(max_features=20_000, stop_words="english", min_df=3,
                            ngram_range=(1, 2), sublinear_tf=True)
    X_tfidf = tfidf.fit_transform(text)

    if backend == "embeddings":
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        X = model.encode(text.tolist(), batch_size=256, show_progress_bar=True,
                         normalize_embeddings=True)
    else:
        n_comp = min(svd_components, X_tfidf.shape[1] - 1)
        X = Normalizer().fit_transform(
            TruncatedSVD(n_comp, random_state=seed).fit_transform(X_tfidf))

    labels = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(X)

    # Name each cluster by its highest-weight TF-IDF terms (works for both backends).
    terms = np.array(tfidf.get_feature_names_out())
    names = {}
    for c in range(k):
        mask = labels == c
        centroid = np.asarray(X_tfidf[mask].mean(axis=0)).ravel()
        names[c] = " / ".join(terms[np.argsort(centroid)[::-1][:3]])
    return labels, names


def topic_leaderboards(
    battles: pd.DataFrame, topic_col: str = "topic", min_battles: int = 300,
    min_model_battles: int = 30,
) -> pd.DataFrame:
    """Fit a BT model inside every topic; return long table (topic, model, rating, rank)."""
    rows = []
    for topic, sub in battles.groupby(topic_col):
        if len(sub) < min_battles:
            continue
        counts = pd.concat([sub["model_a"], sub["model_b"]]).value_counts()
        keep = counts[counts >= min_model_battles].index
        sub = sub[sub["model_a"].isin(keep) & sub["model_b"].isin(keep)]
        if sub["model_a"].nunique() < 3:
            continue
        r, _ = fit_bradley_terry(sub)
        for rank, (model, rating) in enumerate(r.items(), start=1):
            rows.append({"topic": topic, "model": model, "rating": rating,
                         "rank": rank, "n_battles": len(sub)})
    return pd.DataFrame(rows)


def topic_rank_matrix(topic_lb: pd.DataFrame, overall: pd.Series) -> pd.DataFrame:
    """Model x topic rank table, rows ordered by overall rating."""
    mat = topic_lb.pivot_table(index="model", columns="topic", values="rank")
    return mat.reindex([m for m in overall.index if m in mat.index])
