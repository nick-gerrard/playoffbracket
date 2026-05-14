from datetime import datetime, date, timedelta
from sqlmodel import Session, select
from enums import BetStatus, GameStatus, TransactionKind
from models import (
    Game,
    Prediction,
    Series,
    ScoringConfig,
    Team,
    User,
    Season,
    Transaction,
    Bet,
)
import httpx

NHL_BASE = "https://api-web.nhle.com/v1"


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


def fetch_games(session: Session, day: date) -> list[Game]:
    return list(session.exec(select(Game).where(Game.date == day)).all())


def fetch_bets(session: Session, game: int) -> list[Bet]:
    return list(session.exec(select(Bet).where(Bet.game_id == game)).all())


def fetch_bets_for_user(session: Session, user_id: int) -> list[Bet]:
    from sqlalchemy import or_
    return list(session.exec(
        select(Bet).where(or_(Bet.challenger == user_id, Bet.challengee == user_id))
    ).all())


def fetch_bet(session: Session, bet_id: int) -> Bet:
    return session.exec(select(Bet).where(Bet.id == bet_id)).first()  # type: ignore


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


def record_transaction(
    session: Session,
    amount: int,
    kind: TransactionKind,
    payee_id: int | None = None,
    payer_id: int | None = None,
    bet_id: int | None = None,
    note: str | None = None,
):
    payer = session.get(User, payer_id) if payer_id else None
    payee = session.get(User, payee_id) if payee_id else None

    if payer:
        payer.balance -= amount
        session.add(payer)
    if payee:
        payee.balance += amount
        session.add(payee)

    if note:
        desc = note
    else:
        match kind:
            case TransactionKind.SIGNUP_BONUS:
                desc = f"{payee.name} joined — signup bonus"
            case TransactionKind.BET_ESCROW:
                desc = f"{payer.name} escrowed {amount} DB"
            case TransactionKind.BET_WIN:
                desc = f"{payee.name} won {amount} DB (bet #{bet_id})"
            case TransactionKind.BET_REFUND:
                desc = f"{payee.name} refunded — bet #{bet_id} cancelled"
            case TransactionKind.ADMIN_CREDIT:
                desc = f"Admin credited {payee.name} {amount} DB"
            case TransactionKind.BRACKET_BONUS:
                desc = f"{payee.name} awarded bracket prize: {amount} DB"
            case _:
                desc = str(kind)

    session.add(Transaction(payer=payer_id, payee=payee_id, bet_id=bet_id, amount=amount, desc=desc))
    session.commit()


def issue_bet(
    session: Session,
    challenger: int,
    challengee: int,
    amount: int,
    game_id: int,
    winner_id: int,
):
    challenger_user = fetch_user(session, challenger)
    if not challenger_user or challenger_user.balance < amount:
        raise ValueError("Insufficient balance")
    b = Bet(
        challenger=challenger,
        challengee=challengee,
        game_id=game_id,
        amount=amount,
        challenger_winner=winner_id,
    )
    session.add(b)
    session.commit()
    session.refresh(b)
    record_transaction(
        session,
        amount=amount,
        kind=TransactionKind.BET_ESCROW,
        payer_id=challenger,
        bet_id=b.id,
    )


def accept_bet(session: Session, bet_id: int, challengee: int):
    bet = fetch_bet(session, bet_id)
    challengee_user = fetch_user(session, challengee)
    if not challengee_user or challengee_user.balance < bet.amount:
        raise ValueError("Insufficient balance")
    bet.status = BetStatus.ACCEPTED
    session.add(bet)
    record_transaction(
        session=session,
        amount=bet.amount,
        kind=TransactionKind.BET_ESCROW,
        payer_id=challengee,
        bet_id=bet_id,
    )


def decline_bet(session: Session, bet_id: int, challengee: int):
    bet = fetch_bet(session, bet_id)
    if bet.challengee != challengee or bet.status != BetStatus.PENDING:
        raise ValueError("Cannot decline this bet")
    bet.status = BetStatus.CANCELLED
    session.add(bet)
    record_transaction(
        session=session,
        amount=bet.amount,
        kind=TransactionKind.BET_REFUND,
        payer_id=None,
        payee_id=bet.challenger,
        bet_id=bet_id,
    )


def settle_bets(session: Session) -> None:
    yesterday = date.today() - timedelta(days=1)
    games = fetch_games(session, yesterday)
    for game in games:
        if game.winner is None:
            continue
        bets = fetch_bets(session, game.id)
        for bet in bets:
            if bet.status == BetStatus.ACCEPTED:
                bet.status = BetStatus.SETTLED
                session.add(bet)
                if bet.challenger_winner == game.winner:
                    payee = bet.challenger
                else:
                    payee = bet.challengee
                record_transaction(
                    session,
                    payee_id=payee,
                    amount=bet.amount * 2,
                    kind=TransactionKind.BET_WIN,
                    bet_id=bet.id,
                )

            elif bet.status == BetStatus.PENDING:
                bet.status = BetStatus.CANCELLED
                session.add(bet)
                record_transaction(
                    session,
                    payee_id=bet.challenger,
                    amount=bet.amount,
                    kind=TransactionKind.BET_REFUND,
                    bet_id=bet.id,
                )


def signup_bonus(session: Session, payee_id: int, amount: int):
    record_transaction(session, amount=amount, kind=TransactionKind.SIGNUP_BONUS, payee_id=payee_id)


def bracket_bonus(session: Session, payee_id: int, amount: int):
    record_transaction(session, amount=amount, kind=TransactionKind.BRACKET_BONUS, payee_id=payee_id)


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


def compute_max_possible(
    predictions: list[Prediction],
    all_series: list[Series],
    series_results: dict[int, tuple[int | None, str]],
    scoring: dict[str, int],
) -> int:
    eliminated: set[int] = set()
    for s in all_series:
        winner_id = series_results.get(s.id, (None, ""))[0]
        if winner_id is not None:
            if s.top_seed_team and s.top_seed_team != winner_id:
                eliminated.add(s.top_seed_team)
            if s.bottom_seed_team and s.bottom_seed_team != winner_id:
                eliminated.add(s.bottom_seed_team)
    return sum(
        scoring.get(series_results[p.series_id][1], 0)
        for p in predictions
        if p.predicted_winner_id not in eliminated
    )


def _get_or_create_team(session: Session, team_data: dict) -> Team:
    team = session.exec(select(Team).where(Team.api_id == team_data["id"])).first()
    if not team:
        light_logo = team_data.get("logo", "")
        team = Team(
            api_id=team_data["id"],
            name=team_data["name"]["default"],
            abbrev=team_data["abbrev"],
            logo_url=light_logo,
            dark_logo_url=light_logo.replace("_light", "_dark"),
        )
        session.add(team)
        session.commit()
        session.refresh(team)
    return team


def ingest_games(session: Session, target_date: date) -> None:
    date_str = target_date.strftime("%Y-%m-%d")
    data = httpx.get(f"{NHL_BASE}/score/{date_str}").json()

    for g in data.get("games", []):
        if g.get("gameScheduleState") != "OK":
            continue

        home = _get_or_create_team(session, g["homeTeam"])
        away = _get_or_create_team(session, g["awayTeam"])
        existing = session.exec(select(Game).where(Game.api_id == g["id"])).first()

        if existing:
            if g["gameState"] == GameStatus.OFF:
                existing.status = GameStatus.OFF
                existing.home_team_score = g["homeTeam"]["score"]
                existing.away_team_score = g["awayTeam"]["score"]
                existing.outcome = g.get("gameOutcome", {}).get("lastPeriodType")
                existing.winner = (
                    home.id
                    if g["homeTeam"]["score"] > g["awayTeam"]["score"]
                    else away.id
                )
                session.add(existing)
        else:
            start_time = datetime.fromisoformat(
                g["startTimeUTC"].replace("Z", "+00:00")
            )
            session.add(
                Game(
                    api_id=g["id"],
                    date=target_date,
                    start_time=start_time,
                    home_team=home.id,
                    away_team=away.id,
                    status=g["gameState"],
                )
            )

    session.commit()


def daily_job(session: Session) -> None:
    today = date.today()
    yesterday = today - timedelta(days=1)
    ingest_games(session, yesterday)
    ingest_games(session, today)
    settle_bets(session)


def build_leaderboard(
    users: list[User],
    all_predictions: list[Prediction],
    series_results: dict[int, tuple[int | None, str]],
    scoring: dict[str, int],
    all_series: list[Series],
) -> list[dict]:
    user_map = {u.id: u for u in users}
    preds_by_user: dict[int, list[Prediction]] = {}
    for p in all_predictions:
        preds_by_user.setdefault(p.user_id, []).append(p)

    entries = [
        {
            "user": user_map[user_id],
            "score": score_bracket(preds, series_results, scoring),
            "max_possible": compute_max_possible(preds, all_series, series_results, scoring),
        }
        for user_id, preds in preds_by_user.items()
        if user_id in user_map
    ]
    return sorted(entries, key=lambda x: x["score"], reverse=True)
