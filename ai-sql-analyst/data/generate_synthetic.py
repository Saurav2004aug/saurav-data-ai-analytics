"""Generate a synthetic dataset with the exact schema of the Olist Brazilian E-commerce
dataset (Kaggle: olistbr/brazilian-ecommerce).

Why: CI and first-time users can run the whole warehouse without a Kaggle account, and
the generator plants known effects (late deliveries -> low review scores, a small share
of repeat customers, credit-card instalments) so the analyses have something to find.

    python ingestion/generate_synthetic.py --orders 25000 --out data/raw
"""
from __future__ import annotations

import argparse
import string
from pathlib import Path

import numpy as np
import pandas as pd

STATES = {  # state: (share of customers, typical delivery days from SP sellers)
    "SP": (0.42, 8), "RJ": (0.13, 14), "MG": (0.12, 11), "RS": (0.055, 15), "PR": (0.05, 11),
    "SC": (0.037, 14), "BA": (0.034, 18), "DF": (0.021, 12), "ES": (0.02, 15), "GO": (0.02, 15),
    "PE": (0.017, 21), "CE": (0.013, 20), "PA": (0.01, 23), "MT": (0.009, 17), "MA": (0.008, 21),
    "MS": (0.007, 15), "PB": (0.005, 20), "PI": (0.005, 19), "RN": (0.005, 19), "AL": (0.004, 24),
    "SE": (0.003, 21), "TO": (0.003, 17), "RO": (0.0025, 19), "AM": (0.0015, 26),
    "AC": (0.0008, 21), "AP": (0.0007, 27), "RR": (0.0005, 29),
}
CITIES = {"SP": "sao paulo", "RJ": "rio de janeiro", "MG": "belo horizonte", "RS": "porto alegre",
          "PR": "curitiba", "SC": "florianopolis", "BA": "salvador", "DF": "brasilia"}

CATEGORIES = {  # pt name: (english, median price BRL, median weight g, popularity)
    "cama_mesa_banho": ("bed_bath_table", 80, 1500, 0.11),
    "beleza_saude": ("health_beauty", 110, 800, 0.10),
    "esporte_lazer": ("sports_leisure", 100, 1200, 0.09),
    "moveis_decoracao": ("furniture_decor", 90, 3000, 0.08),
    "informatica_acessorios": ("computers_accessories", 120, 700, 0.08),
    "utilidades_domesticas": ("housewares", 70, 1500, 0.07),
    "relogios_presentes": ("watches_gifts", 180, 400, 0.06),
    "telefonia": ("telephony", 70, 300, 0.05),
    "ferramentas_jardim": ("garden_tools", 100, 2500, 0.04),
    "automotivo": ("auto", 120, 1500, 0.04),
    "brinquedos": ("toys", 90, 1000, 0.04),
    "cool_stuff": ("cool_stuff", 150, 1500, 0.04),
    "perfumaria": ("perfumery", 110, 500, 0.035),
    "bebes": ("baby", 110, 2000, 0.03),
    "eletronicos": ("electronics", 60, 400, 0.025),
    "papelaria": ("stationery", 70, 800, 0.025),
    "fashion_bolsas_e_acessorios": ("fashion_bags_accessories", 80, 500, 0.02),
    "pet_shop": ("pet_shop", 90, 1500, 0.02),
    "eletroportateis": ("small_appliances", 200, 3000, 0.02),
    "construcao_ferramentas_construcao": ("construction_tools_construction", 110, 2500, 0.015),
    "pcs": ("computers", 1100, 6000, 0.005),
}


def _hex_ids(rng: np.random.Generator, n: int) -> np.ndarray:
    """32-char hex ids like Olist's (unique)."""
    ids = set()
    alphabet = np.array(list(string.hexdigits[:16]))
    while len(ids) < n:
        ids.update("".join(x) for x in rng.choice(alphabet, (n - len(ids), 32)))
    return np.array(sorted(ids))[rng.permutation(n)]


def _fmt(ts: pd.Series) -> pd.Series:
    return ts.dt.strftime("%Y-%m-%d %H:%M:%S").where(ts.notna(), None)


def generate(n_orders: int = 25_000, seed: int = 42) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)

    # ---------------- products / sellers --------------------------------------
    cats = list(CATEGORIES)
    pop = np.array([CATEGORIES[c][3] for c in cats])
    n_products = max(500, n_orders // 8)
    prod_cat = rng.choice(cats, n_products, p=pop / pop.sum())
    products = pd.DataFrame({
        "product_id": _hex_ids(rng, n_products),
        "product_category_name": prod_cat,
        "product_name_lenght": rng.integers(20, 64, n_products),
        "product_description_lenght": rng.integers(100, 3000, n_products),
        "product_photos_qty": rng.integers(1, 7, n_products),
        "product_weight_g": np.round([rng.lognormal(np.log(CATEGORIES[c][2]), 0.7) for c in prod_cat]),
        "product_length_cm": rng.integers(15, 80, n_products),
        "product_height_cm": rng.integers(2, 50, n_products),
        "product_width_cm": rng.integers(10, 60, n_products),
    })
    products.loc[rng.random(n_products) < 0.015, "product_category_name"] = None  # real data has gaps
    base_price = np.array([rng.lognormal(np.log(CATEGORIES[c][1]), 0.6) for c in prod_cat]).round(2)

    n_sellers = max(100, n_orders // 30)
    seller_state = rng.choice(["SP", "MG", "PR", "RJ", "SC", "RS"], n_sellers,
                              p=[0.6, 0.08, 0.11, 0.05, 0.07, 0.09])
    sellers = pd.DataFrame({
        "seller_id": _hex_ids(rng, n_sellers),
        "seller_zip_code_prefix": rng.integers(1000, 99999, n_sellers),
        "seller_city": [CITIES.get(s, "outra cidade") for s in seller_state],
        "seller_state": seller_state,
    })
    seller_quality = rng.normal(0, 1, n_sellers)  # hidden: some sellers ship slowly

    # ---------------- customers / orders --------------------------------------
    n_unique = int(n_orders * 0.93)
    unique_ids = _hex_ids(rng, n_unique)
    st = list(STATES)
    share = np.array([STATES[s][0] for s in st])
    cust_state = rng.choice(st, n_unique, p=share / share.sum())
    # ~6% of people order again; each order gets a fresh customer_id (as in Olist)
    who = np.concatenate([np.arange(n_unique),
                          rng.choice(n_unique, n_orders - n_unique, replace=True)])
    rng.shuffle(who)

    # Volume grows over time (Olist grew ~10x from late 2016 to 2018).
    start, end = pd.Timestamp("2016-10-01"), pd.Timestamp("2018-08-31")
    span = (end - start).total_seconds()
    u = rng.random(n_orders) ** 0.55
    purchase = start + pd.to_timedelta(np.sort(u) * span, unit="s")
    purchase = pd.Series(purchase).dt.floor("s")

    n = n_orders
    order_ids = _hex_ids(rng, n)
    customer_ids = _hex_ids(rng, n)
    customers = pd.DataFrame({
        "customer_id": customer_ids,
        "customer_unique_id": unique_ids[who],
        "customer_zip_code_prefix": rng.integers(1000, 99999, n),
        "customer_city": [CITIES.get(s, "outra cidade") for s in cust_state[who]],
        "customer_state": cust_state[who],
    })

    status = rng.choice(["delivered", "shipped", "canceled", "unavailable", "invoiced",
                         "processing", "created", "approved"], n,
                        p=[0.970, 0.011, 0.0063, 0.0061, 0.0032, 0.003, 0.0002, 0.0002])
    approved = purchase + pd.to_timedelta(rng.exponential(10, n), unit="h")
    carrier = approved + pd.to_timedelta(rng.gamma(2, 1.4, n), unit="D")

    # ---------------- items ----------------------------------------------------
    n_items = rng.choice([1, 2, 3, 4], n, p=[0.90, 0.075, 0.018, 0.007])
    item_order = np.repeat(np.arange(n), n_items)
    item_seq = np.concatenate([np.arange(1, k + 1) for k in n_items])
    prod_idx = rng.integers(0, n_products, len(item_order))
    # multi-item orders usually repeat the same product/seller
    same = (item_seq > 1) & (rng.random(len(item_order)) < 0.7)
    prod_idx[same] = prod_idx[np.where(same)[0] - 1]
    seller_idx = rng.integers(0, n_sellers, len(item_order))
    seller_idx[same] = seller_idx[np.where(same)[0] - 1]
    price = (base_price[prod_idx] * rng.uniform(0.9, 1.1, len(prod_idx))).round(2)
    weight = products["product_weight_g"].to_numpy()[prod_idx]
    freight = (8 + 0.004 * weight + rng.gamma(2, 3, len(prod_idx))).round(2)
    items = pd.DataFrame({
        "order_id": order_ids[item_order],
        "order_item_id": item_seq,
        "product_id": products["product_id"].to_numpy()[prod_idx],
        "seller_id": sellers["seller_id"].to_numpy()[seller_idx],
        "shipping_limit_date": _fmt(pd.Series(approved.values[item_order]) + pd.Timedelta(days=6)),
        "price": price,
        "freight_value": freight,
    })
    # orders that never got items (unavailable) - as in real data
    no_items = status == "unavailable"
    items = items[~np.isin(items["order_id"], order_ids[no_items])]

    # delivery time: state distance + slow sellers + noise; estimate is generous
    first_seller = pd.Series(seller_idx).groupby(item_order).first().reindex(range(n)).fillna(0).astype(int)
    typical = np.array([STATES[s][1] for s in cust_state[who]])
    transit = rng.gamma(4, typical / 4) + np.maximum(0, seller_quality[first_seller]) * 3
    delivered = carrier + pd.to_timedelta(transit, unit="D")
    estimated = (purchase + pd.to_timedelta(typical * 1.9 + rng.integers(3, 12, n), unit="D")).dt.normalize()
    # Seasonal crunch: Black Friday 2017 and the Feb-Mar 2018 truckers' strikes ran late.
    crunch = (((purchase >= "2017-11-20") & (purchase <= "2017-12-10"))
              | ((purchase >= "2018-02-15") & (purchase <= "2018-03-20")))
    delivered = delivered + pd.to_timedelta(np.where(crunch, rng.gamma(2, 4, n), 0), unit="D")

    delivered_ok = status == "delivered"
    shipped_ok = np.isin(status, ["delivered", "shipped"])
    orders = pd.DataFrame({
        "order_id": order_ids,
        "customer_id": customer_ids,
        "order_status": status,
        "order_purchase_timestamp": _fmt(purchase),
        "order_approved_at": _fmt(approved.where(~np.isin(status, ["created"]))),
        "order_delivered_carrier_date": _fmt(pd.Series(carrier).where(shipped_ok)),
        "order_delivered_customer_date": _fmt(pd.Series(delivered).where(delivered_ok)),
        "order_estimated_delivery_date": _fmt(estimated),
    })

    # ---------------- payments -------------------------------------------------
    totals = items.groupby("order_id")[["price", "freight_value"]].sum().sum(axis=1)
    order_total = pd.Series(order_ids).map(totals).fillna(0).to_numpy()
    order_total = np.where(order_total == 0, rng.uniform(30, 200, n), order_total).round(2)
    ptype = rng.choice(["credit_card", "boleto", "voucher", "debit_card"], n,
                       p=[0.74, 0.19, 0.055, 0.015])
    pay_rows = []
    for oid, total, pt in zip(order_ids, order_total, ptype):
        if pt == "voucher" and rng.random() < 0.6:          # voucher + card split
            v = round(total * rng.uniform(0.1, 0.6), 2)
            pay_rows += [(oid, 1, "voucher", 1, v), (oid, 2, "credit_card",
                         int(rng.integers(1, 6)), round(total - v, 2))]
        else:
            inst = int(min(10, max(1, rng.poisson(total / 60)))) if pt == "credit_card" else 1
            pay_rows.append((oid, 1, pt, inst, total))
    payments = pd.DataFrame(pay_rows, columns=["order_id", "payment_sequential", "payment_type",
                                               "payment_installments", "payment_value"])

    # ---------------- reviews --------------------------------------------------
    late_days = (pd.Series(delivered) - pd.Series(estimated)).dt.days.to_numpy()
    late = delivered_ok & (late_days > 0)
    score = np.where(
        late,
        rng.choice([1, 2, 3, 4, 5], n, p=[0.46, 0.10, 0.12, 0.12, 0.20]),
        rng.choice([1, 2, 3, 4, 5], n, p=[0.06, 0.02, 0.07, 0.20, 0.65]),
    )
    score = np.where(np.isin(status, ["canceled", "unavailable"]),
                     rng.choice([1, 2, 3], n, p=[0.8, 0.1, 0.1]), score)
    has_review = rng.random(n) > 0.008
    review_date = pd.Series(np.where(delivered_ok, delivered, estimated)).dt.normalize() + pd.Timedelta(days=1)
    reviews = pd.DataFrame({
        "review_id": _hex_ids(rng, n), "order_id": order_ids, "review_score": score,
        "review_comment_title": None,
        "review_comment_message": np.where(score <= 2, "produto nao chegou", None),
        "review_creation_date": _fmt(review_date),
        "review_answer_timestamp": _fmt(review_date + pd.to_timedelta(rng.exponential(2, n), unit="D")),
    })[has_review]
    # ~0.5% of orders get a second, later review (the real dataset has these duplicates)
    dup = reviews.sample(frac=0.005, random_state=seed).copy()
    dup["review_id"] = _hex_ids(rng, len(dup))
    dup["review_creation_date"] = _fmt(pd.to_datetime(dup["review_creation_date"]) + pd.Timedelta(days=3))
    reviews = pd.concat([reviews, dup], ignore_index=True)

    translation = pd.DataFrame({"product_category_name": cats,
                                "product_category_name_english": [CATEGORIES[c][0] for c in cats]})

    return {
        "olist_customers_dataset": customers,
        "olist_orders_dataset": orders,
        "olist_order_items_dataset": items,
        "olist_order_payments_dataset": payments,
        "olist_order_reviews_dataset": reviews,
        "olist_products_dataset": products,
        "olist_sellers_dataset": sellers,
        "product_category_name_translation": translation,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders", type=int, default=25_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/raw")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in generate(args.orders, args.seed).items():
        df.to_csv(out / f"{name}.csv", index=False)
        print(f"{name:40s} {len(df):>8,} rows")


if __name__ == "__main__":
    main()
