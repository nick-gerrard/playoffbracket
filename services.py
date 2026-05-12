from sqlmodel import Session, select
from models import Prediction, Series, ScoringConfig, User, Season, Transaction


# --- Query functions ---


def fetch_current_season(session: Session) -> Season | None:
    return session.exec(select(Season).order_by(Season.year.desc())).first()  # type: ignore


def fetch_season_by_year(session: Session, year: int) -> Season | None:
    return session.exec(select(Season).where(Season.year == year)).first()


def fetch_all_users(session: Session) -> list[User]:
    return list(session.exec(select(User)).all())


def fetch_user(session: Session, user_id: int) -> User | None:
    return session.exec(select(User).where(User.id == user_id)).first()


def fetch_all_transactions(session: Session) -> list[Transaction]:
    return list(session.exec(select(Transaction)).all())


def fetch_predictions(
    session: Session, user_id: int, season_id: int
) -> list[Prediction]:
    return list(
        session.exec(
            select(Prediction)
            .join(Series, Prediction.series_id == Series.id)  # type: ignore
            .where(Prediction.user_id == user_id, Series.season_id == season_id)
        ).all()
    )


def fetch_predictions_for_season(session: Session, season_id: int) -> list[Prediction]:
    return list(
        session.exec(
            select(Prediction)
            .join(Series, Prediction.series_id == Series.id)  # type: ignore
            .where(Series.season_id == season_id)
        ).all()
    )


def fetch_series_results(
    session: Session, season_id: int
) -> dict[int, tuple[int | None, str]]:
    return {
        s.id: (s.winner, s.series_abbrev)
        for s in session.exec(select(Series).where(Series.season_id == season_id)).all()
    }  # type: ignore


def fetch_scoring(session: Session, season_year: int) -> dict[str, int]:
    return {
        sc.series_abbrev: sc.points
        for sc in session.exec(
            select(ScoringConfig).where(ScoringConfig.season_year == season_year)
        ).all()
    }


def get_predictions_map(
    session: Session, user_id: int, season_id: int
) -> dict[int, int]:
    return {
        p.series_id: p.predicted_winner_id
        for p in fetch_predictions(session, user_id, season_id)
    }


def has_prediction(session: Session, user_id: int, season_id: int) -> bool:
    return (
        session.exec(
            select(Prediction)
            .join(Series, Prediction.series_id == Series.id)  # type: ignore
            .where(Prediction.user_id == user_id, Series.season_id == season_id)
        ).first()
        is not None
    )


def save_prediction(session: Session, user_id: int, predictions: list[dict]) -> None:
    for p in predictions:
        session.add(
            Prediction(
                user_id=user_id,
                series_id=p["series_id"],
                predicted_winner_id=p["winner_id"],
            )
        )
    session.commit()


def transaction(
    session: Session, payee_id: int, amount: int, desc: str, payer_id: int | None = None
):
    if payer_id:
        payer: User = fetch_user(session, payer_id)  # type: ignore
        payer.balance -= amount
        session.add(payer)
    payee: User = fetch_user(session, payee_id)  # type: ignore
    payee.balance += amount
    session.add(payee)
    t = Transaction(payer=payer_id, payee=payee_id, amount=amount, desc=desc)
    session.add(t)
    session.commit()


def signup_bonus(session: Session, payee_id: int, amount: int):
    desc = f"{payee_id} has recieved {amount} DucksBucks for signing up!"
    transaction(session, payee_id, amount, desc)


def bracket_bonus(session: Session, payee_id: int, amount: int):
    desc = f"{payee_id} has recieved {amount} DucksBucks for completing a bracket!"
    transaction(session, payee_id, amount, desc)


# --- Computation functions ---


def score_bracket(
    predictions: list[Prediction],
    series_results: dict[int, tuple[int | None, str]],
    scoring: dict[str, int],
) -> int:
    return sum(
        scoring.get(series_results[p.series_id][1], 0)
        for p in predictions
        if series_results[p.series_id][0] == p.predicted_winner_id
    )


def build_leaderboard(
    users: list[User],
    all_predictions: list[Prediction],
    series_results: dict[int, tuple[int | None, str]],
    scoring: dict[str, int],
) -> list[dict]:
    user_map = {u.id: u for u in users}
    preds_by_user: dict[int, list[Prediction]] = {}
    for p in all_predictions:
        preds_by_user.setdefault(p.user_id, []).append(p)

    entries = [
        {
            "user": user_map[user_id],
            "score": score_bracket(preds, series_results, scoring),
        }
        for user_id, preds in preds_by_user.items()
        if user_id in user_map
    ]
    return sorted(entries, key=lambda x: x["score"], reverse=True)
