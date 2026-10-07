"""End-to-end pipeline: load -> clean -> rate -> bias -> topics -> judge -> report.

Examples
--------
    # real data (needs `huggingface-cli login` and accepted dataset terms)
    python scripts/run_pipeline.py --source hf --bootstrap 200

    # real data + real LLM judge on 300 battles (needs ANTHROPIC_API_KEY)
    python scripts/run_pipeline.py --source hf --judge anthropic --judge-n 300

    # fully offline demo on simulated data with known ground truth
    python scripts/run_pipeline.py --source synthetic
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scipy.stats import spearmanr  # noqa: E402

from arena_eval import bias, data, judge, ratings, report, topics  # noqa: E402

log = logging.getLogger("pipeline")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["hf", "synthetic", "file"], default="hf")
    ap.add_argument("--file", help="path to a cleaned battles table (with --source file)")
    ap.add_argument("--bootstrap", type=int, default=200)
    ap.add_argument("--topics", type=int, default=8)
    ap.add_argument("--topic-backend", choices=["tfidf", "embeddings"], default="tfidf")
    ap.add_argument("--judge", choices=["mock", "anthropic"], default="mock")
    ap.add_argument("--judge-model", default="claude-haiku-4-5")
    ap.add_argument("--judge-n", type=int, default=300)
    ap.add_argument("--out", default=str(ROOT / "reports"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    out = Path(args.out)
    fig_dir = out / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. Load --------------------------------------------------------------
    if args.source == "hf":
        battles, source = data.load_arena_hf(), "lmsys/chatbot_arena_conversations (Hugging Face)"
    elif args.source == "file":
        battles, source = data.load_table(args.file), args.file
    else:
        battles, source = data.make_synthetic_battles(), "synthetic simulator (known ground truth)"
    data.save_table(battles.drop(columns=["response_a", "response_b"]), ROOT / "data" / "battles_clean")
    models = sorted(set(battles["model_a"]) | set(battles["model_b"]))
    log.info("Loaded %s battles, %s models from %s", f"{len(battles):,}", len(models), source)

    # 2. Ratings -----------------------------------------------------------
    bt, _ = ratings.fit_bradley_terry(battles)
    elo = ratings.online_elo(battles)
    boot = ratings.bootstrap_ratings(battles, n_boot=args.bootstrap)
    lb = ratings.summarize_bootstrap(boot, bt)
    styled, _ = ratings.fit_bradley_terry(battles, ratings.length_style_features(battles))
    log.info("Ratings done (top: %s)", lb.index[0])

    # 3. Bias diagnostics --------------------------------------------------
    pos = bias.position_bias(battles)
    length = bias.length_bias(battles)
    curve = bias.length_win_curve(battles)
    ties = bias.tie_rate_by_gap(battles, bt)
    shift = bias.style_rank_shift(bt, styled)
    log.info("Bias: A-share %.3f, longer-wins %.3f", pos["a_win_share"], length["longer_win_share"])

    # 4. Topics ------------------------------------------------------------
    labels, names = topics.cluster_prompts(battles["prompt"], k=args.topics, backend=args.topic_backend)
    battles["topic"] = [names[c] for c in labels]
    topic_lb = topics.topic_leaderboards(battles)
    topic_mat = topics.topic_rank_matrix(topic_lb, bt)
    log.info("Topics: %s", sorted(set(names.values())))
    topic_ari = None
    if "true_topic" in battles:  # simulator only: score clustering against ground truth
        from sklearn.metrics import adjusted_rand_score
        topic_ari = float(adjusted_rand_score(battles["true_topic"], labels))
        log.info("Topic clustering ARI vs ground truth: %.3f", topic_ari)

    # 5. LLM-as-judge ------------------------------------------------------
    sample = judge.sample_for_judging(battles, n=args.judge_n)
    jres = judge.run_judge(sample, backend=args.judge, model=args.judge_model,
                           cache_path=out / f"judge_{args.judge}.jsonl" if args.judge != "mock" else None)
    jscore = judge.score_judge(jres)
    log.info("Judge (%s): kappa %.3f", args.judge, jscore["cohen_kappa"])

    # 6. Persist tables for the dashboard ---------------------------------
    tables = out / "tables"
    data.save_table(lb.reset_index(names="model"), tables / "leaderboard")
    data.save_table(boot, tables / "bootstrap")
    data.save_table(elo.rename_axis("model").reset_index(), tables / "online_elo")
    data.save_table(ratings.predicted_win_matrix(bt).reset_index(names="model"), tables / "win_matrix_pred")
    data.save_table(ratings.observed_win_matrix(battles).reset_index(names="model"), tables / "win_matrix_obs")
    data.save_table(ratings.battle_counts(battles).reset_index(names="model"), tables / "battle_counts")
    data.save_table(curve, tables / "length_curve")
    data.save_table(ties, tables / "tie_by_gap")
    data.save_table(shift.reset_index(names="model"), tables / "style_shift")
    data.save_table(topic_lb, tables / "topic_leaderboards")
    data.save_table(jres, tables / "judge_results")

    # 7. Report ------------------------------------------------------------
    figs = [
        report.fig_leaderboard(lb, fig_dir),
        report.fig_win_matrix(ratings.predicted_win_matrix(bt), fig_dir),
        report.fig_length_curve(curve, fig_dir),
        report.fig_style_shift(shift, fig_dir),
        report.fig_topic_ranks(topic_mat, fig_dir),
        report.fig_judge_confusion(jscore["confusion_matrix"], fig_dir, jscore["backend"]),
    ]
    metrics = {
        "source": source, "n_battles": len(battles), "n_models": len(models),
        "n_boot": args.bootstrap, "position": pos, "length": length,
        "elo_bt_spearman": float(spearmanr(bt.loc[models], elo.loc[models]).statistic),
        "topic_ari": topic_ari, "judge": jscore,
    }
    path = report.write_summary(out, metrics, lb, shift, figs)
    log.info("Report written to %s  (%.1fs)", path, time.time() - t0)


if __name__ == "__main__":
    main()
