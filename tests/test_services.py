import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from sqlmodel import Session, select

from models import User, Bet, Transaction, Prediction, Series
from enums import BetStatus, TransactionKind
from services import (
    score_bracket,
    compute_max_possible,
    build_leaderboard,
    build_bracket_rounds,
    build_compare_rounds,
    build_series_picker,
    issue_bet,
    accept_bet,
    decline_bet,
    settle_bets,
    record_transaction,
    get_or_create_user,
    toggle_picks_open,
    fetch_users_by_balance,
    fetch_recent_transactions,
    fetch_todays_games,
    count_pending_challenges,
    fetch_pending_challenges,
    fetch_pending_issued,
    fetch_active_bets,
)


# --- Pure computation ---

class TestScoreBracket:
    def test_correct_pick_scores_points(self, team_home, team_away, series, scoring):
        predictions = [Prediction(user_id=1, series_id=series.id, predicted_winner_id=team_home.id)]
        results = {series.id: (team_home.id, "R1A")}
        assert score_bracket(predictions, results, {"R1A": 10}) == 10

    def test_incorrect_pick_scores_zero(self, team_home, team_away, series):
        predictions = [Prediction(user_id=1, series_id=series.id, predicted_winner_id=team_away.id)]
        results = {series.id: (team_home.id, "R1A")}
        assert score_bracket(predictions, results, {"R1A": 10}) == 0

    def test_pending_series_scores_zero(self, series):
        predictions = [Prediction(user_id=1, series_id=series.id, predicted_winner_id=1)]
        results = {series.id: (None, "R1A")}
        assert score_bracket(predictions, results, {"R1A": 10}) == 0

    def test_multiple_picks(self, team_home, team_away, series, season, session):
        series2 = Series(
            title="Series B", series_letter="B", series_abbrev="R1B",
            conference="West", playoff_round=1, season_id=season.id,
            top_seed_team=team_home.id, bottom_seed_team=team_away.id,
        )
        session.add(series2)
        session.commit()
        session.refresh(series2)
        predictions = [
            Prediction(user_id=1, series_id=series.id, predicted_winner_id=team_home.id),
            Prediction(user_id=1, series_id=series2.id, predicted_winner_id=team_away.id),
        ]
        results = {series.id: (team_home.id, "R1A"), series2.id: (team_home.id, "R1B")}
        scoring = {"R1A": 10, "R1B": 10}
        assert score_bracket(predictions, results, scoring) == 10


class TestComputeMaxPossible:
    def test_all_pending_counts_all(self, series, team_home, team_away):
        all_series = [series]
        predictions = [Prediction(user_id=1, series_id=series.id, predicted_winner_id=team_home.id)]
        results = {series.id: (None, "R1A")}
        assert compute_max_possible(predictions, all_series, results, {"R1A": 10}) == 10

    def test_correct_settled_counts(self, series, team_home):
        all_series = [series]
        predictions = [Prediction(user_id=1, series_id=series.id, predicted_winner_id=team_home.id)]
        results = {series.id: (team_home.id, "R1A")}
        assert compute_max_possible(predictions, all_series, results, {"R1A": 10}) == 10

    def test_eliminated_team_counts_zero(self, series, team_home, team_away):
        all_series = [series]
        predictions = [Prediction(user_id=1, series_id=series.id, predicted_winner_id=team_away.id)]
        results = {series.id: (team_home.id, "R1A")}
        assert compute_max_possible(predictions, all_series, results, {"R1A": 10}) == 0


class TestBuildSeriesPicker:
    def test_builds_dict_keyed_by_letter(self, series, team_home, team_away):
        team_map = {team_home.id: team_home, team_away.id: team_away}
        result = build_series_picker([series], team_map)
        assert "A" in result
        assert result["A"]["id"] == series.id
        assert result["A"]["top"]["abbrev"] == "HOM"
        assert result["A"]["bottom"]["abbrev"] == "AWY"

    def test_missing_team_returns_none(self, series):
        result = build_series_picker([series], {})
        assert result["A"]["top"] is None
        assert result["A"]["bottom"] is None


class TestBuildBracketRounds:
    def test_groups_by_round_label(self, series, team_home, team_away, scoring):
        predictions = [Prediction(user_id=1, series_id=series.id, predicted_winner_id=team_home.id)]
        team_map = {team_home.id: team_home, team_away.id: team_away}
        results = {series.id: (None, "R1A")}
        rounds = build_bracket_rounds(predictions, [series], results, team_map, {"R1A": 10})
        assert "First Round" in rounds
        assert rounds["First Round"][0]["letter"] == "A"

    def test_correct_status(self, series, team_home, team_away):
        series.winner = team_home.id
        predictions = [Prediction(user_id=1, series_id=series.id, predicted_winner_id=team_home.id)]
        team_map = {team_home.id: team_home, team_away.id: team_away}
        results = {series.id: (team_home.id, "R1A")}
        rounds = build_bracket_rounds(predictions, [series], results, team_map, {"R1A": 10})
        assert rounds["First Round"][0]["status"] == "correct"

    def test_wrong_status(self, series, team_home, team_away):
        series.winner = team_home.id
        predictions = [Prediction(user_id=1, series_id=series.id, predicted_winner_id=team_away.id)]
        team_map = {team_home.id: team_home, team_away.id: team_away}
        results = {series.id: (team_home.id, "R1A")}
        rounds = build_bracket_rounds(predictions, [series], results, team_map, {"R1A": 10})
        assert rounds["First Round"][0]["status"] == "wrong"

    def test_pending_status(self, series, team_home, team_away):
        predictions = [Prediction(user_id=1, series_id=series.id, predicted_winner_id=team_home.id)]
        team_map = {team_home.id: team_home, team_away.id: team_away}
        results = {series.id: (None, "R1A")}
        rounds = build_bracket_rounds(predictions, [series], results, team_map, {"R1A": 10})
        assert rounds["First Round"][0]["status"] == "pending"


class TestBuildCompareRounds:
    def test_match_when_same_pick(self, series, team_home, team_away):
        team_map = {team_home.id: team_home, team_away.id: team_away}
        preds_a = {series.id: team_home.id}
        preds_b = {series.id: team_home.id}
        rounds = build_compare_rounds([series], preds_a, preds_b, team_map, {})
        assert rounds["First Round"][0]["match"] is True

    def test_no_match_when_different_picks(self, series, team_home, team_away):
        team_map = {team_home.id: team_home, team_away.id: team_away}
        preds_a = {series.id: team_home.id}
        preds_b = {series.id: team_away.id}
        rounds = build_compare_rounds([series], preds_a, preds_b, team_map, {})
        assert rounds["First Round"][0]["match"] is False

    def test_correct_flags(self, series, team_home, team_away):
        series.winner = team_home.id
        team_map = {team_home.id: team_home, team_away.id: team_away}
        preds_a = {series.id: team_home.id}
        preds_b = {series.id: team_away.id}
        rounds = build_compare_rounds([series], preds_a, preds_b, team_map, {})
        entry = rounds["First Round"][0]
        assert entry["correct_a"] is True
        assert entry["correct_b"] is False


# --- DB-backed service functions ---

class TestRecordTransaction:
    def test_credits_payee(self, session, user):
        initial = user.balance
        record_transaction(session, amount=100, kind=TransactionKind.SIGNUP_BONUS, payee_id=user.id)
        session.refresh(user)
        assert user.balance == initial + 100

    def test_debits_payer(self, session, user):
        initial = user.balance
        record_transaction(session, amount=100, kind=TransactionKind.BET_ESCROW, payer_id=user.id)
        session.refresh(user)
        assert user.balance == initial - 100

    def test_creates_transaction_record(self, session, user):
        record_transaction(session, amount=50, kind=TransactionKind.SIGNUP_BONUS, payee_id=user.id)
        txns = list(session.exec(select(Transaction)).all())
        assert len(txns) == 1
        assert txns[0].amount == 50


class TestIssueBet:
    def test_success_creates_bet_and_escrows(self, session, user, other_user, future_game, team_home):
        initial = user.balance
        issue_bet(session, challenger=user.id, challengee=other_user.id,
                  amount=100, game_id=future_game.id, winner_id=team_home.id)
        session.refresh(user)
        bet = session.exec(select(Bet)).first()
        assert bet is not None
        assert bet.status == BetStatus.PENDING
        assert user.balance == initial - 100

    def test_insufficient_balance_raises(self, session, user, other_user, future_game, team_home):
        with pytest.raises(ValueError, match="Insufficient balance"):
            issue_bet(session, challenger=user.id, challengee=other_user.id,
                      amount=9999, game_id=future_game.id, winner_id=team_home.id)


class TestAcceptBet:
    def test_success_escrows_challengee(self, session, pending_bet, other_user):
        initial = other_user.balance
        accept_bet(session, bet_id=pending_bet.id, challengee=other_user.id)
        session.refresh(pending_bet)
        session.refresh(other_user)
        assert pending_bet.status == BetStatus.ACCEPTED
        assert other_user.balance == initial - pending_bet.amount

    def test_window_closed_raises(self, session, past_game, user, other_user, team_home):
        bet = Bet(challenger=user.id, challengee=other_user.id,
                  game_id=past_game.id, amount=50, challenger_winner=team_home.id)
        session.add(bet)
        session.commit()
        session.refresh(bet)
        with pytest.raises(ValueError, match="Betting window has closed"):
            accept_bet(session, bet_id=bet.id, challengee=other_user.id)

    def test_insufficient_balance_raises(self, session, user, future_game, team_home):
        broke = User(name="Broke", email="broke@example.com", balance=0)
        session.add(broke)
        session.commit()
        session.refresh(broke)
        bet = Bet(challenger=user.id, challengee=broke.id,
                  game_id=future_game.id, amount=100, challenger_winner=team_home.id)
        session.add(bet)
        session.commit()
        session.refresh(bet)
        with pytest.raises(ValueError, match="Insufficient balance"):
            accept_bet(session, bet_id=bet.id, challengee=broke.id)


class TestDeclineBet:
    def test_success_refunds_challenger(self, session, pending_bet, other_user, user):
        initial = user.balance
        decline_bet(session, bet_id=pending_bet.id, challengee=other_user.id)
        session.refresh(pending_bet)
        session.refresh(user)
        assert pending_bet.status == BetStatus.CANCELLED
        assert user.balance == initial + pending_bet.amount

    def test_wrong_user_raises(self, session, pending_bet, user):
        with pytest.raises(ValueError, match="Cannot decline"):
            decline_bet(session, bet_id=pending_bet.id, challengee=user.id)


class TestSettleBets:
    def test_challenger_wins_payout(self, session, user, other_user, past_game, team_home):
        past_game.winner = team_home.id
        session.add(past_game)
        bet = Bet(
            challenger=user.id, challengee=other_user.id,
            game_id=past_game.id, amount=100,
            challenger_winner=team_home.id, status=BetStatus.ACCEPTED,
        )
        session.add(bet)
        session.commit()
        initial = user.balance
        settle_bets(session)
        session.refresh(user)
        session.refresh(bet)
        assert bet.status == BetStatus.SETTLED
        assert user.balance == initial + 200

    def test_challengee_wins_payout(self, session, user, other_user, past_game, team_home, team_away):
        past_game.winner = team_away.id
        session.add(past_game)
        bet = Bet(
            challenger=user.id, challengee=other_user.id,
            game_id=past_game.id, amount=100,
            challenger_winner=team_home.id, status=BetStatus.ACCEPTED,
        )
        session.add(bet)
        session.commit()
        initial = other_user.balance
        settle_bets(session)
        session.refresh(other_user)
        assert other_user.balance == initial + 200

    def test_pending_bet_cancelled_and_refunded(self, session, user, other_user, past_game, team_home):
        past_game.winner = team_home.id
        session.add(past_game)
        bet = Bet(
            challenger=user.id, challengee=other_user.id,
            game_id=past_game.id, amount=100,
            challenger_winner=team_home.id, status=BetStatus.PENDING,
        )
        session.add(bet)
        user.balance -= 100
        session.add(user)
        session.commit()
        initial = user.balance
        settle_bets(session)
        session.refresh(user)
        session.refresh(bet)
        assert bet.status == BetStatus.CANCELLED
        assert user.balance == initial + 100


class TestGetOrCreateUser:
    def test_creates_new_user_with_bonus(self, session):
        user, created = get_or_create_user(session, email="new@example.com", name="New User", bonus_amount=500)
        assert created is True
        assert user.id is not None
        assert user.balance == 500

    def test_returns_existing_user(self, session, user):
        existing, created = get_or_create_user(session, email=user.email, name=user.name, bonus_amount=500)
        assert created is False
        assert existing.id == user.id
        session.refresh(user)
        assert user.balance == 1000  # unchanged


class TestTogglePicksOpen:
    def test_closes_open_season(self, session, season):
        assert season.picks_open is True
        toggle_picks_open(session)
        session.refresh(season)
        assert season.picks_open is False

    def test_opens_closed_season(self, session, season):
        season.picks_open = False
        session.add(season)
        session.commit()
        toggle_picks_open(session)
        session.refresh(season)
        assert season.picks_open is True


class TestFetchUsersBy:
    def test_fetch_users_by_balance_ordered(self, session, user, other_user):
        user.balance = 500
        other_user.balance = 1500
        session.add(user)
        session.add(other_user)
        session.commit()
        from services import fetch_users_by_balance
        result = fetch_users_by_balance(session)
        assert result[0].balance >= result[1].balance

    def test_fetch_recent_transactions_limit(self, session, user):
        for i in range(25):
            record_transaction(session, amount=1, kind=TransactionKind.SIGNUP_BONUS, payee_id=user.id)
        result = fetch_recent_transactions(session, limit=10)
        assert len(result) == 10

    def test_fetch_recent_transactions_most_recent_first(self, session, user):
        for amount in [10, 20, 30]:
            record_transaction(session, amount=amount, kind=TransactionKind.SIGNUP_BONUS, payee_id=user.id)
        result = fetch_recent_transactions(session, limit=3)
        assert result[0].amount == 30


class TestCountAndFetchPending:
    def test_count_pending_challenges(self, session, pending_bet, other_user):
        assert count_pending_challenges(session, other_user.id) == 1

    def test_fetch_pending_challenges(self, session, pending_bet, other_user):
        result = fetch_pending_challenges(session, other_user.id)
        assert len(result) == 1
        assert result[0].id == pending_bet.id

    def test_fetch_pending_issued(self, session, pending_bet, user):
        result = fetch_pending_issued(session, user.id)
        assert len(result) == 1
        assert result[0].id == pending_bet.id

    def test_fetch_active_bets(self, session, pending_bet, user, other_user):
        pending_bet.status = BetStatus.ACCEPTED
        session.add(pending_bet)
        session.commit()
        result = fetch_active_bets(session, user.id)
        assert len(result) == 1

    def test_fetch_active_bets_excludes_pending(self, session, pending_bet, user):
        result = fetch_active_bets(session, user.id)
        assert len(result) == 0


class TestFetchTodaysGames:
    def test_returns_todays_games(self, session, future_game):
        games, bettable_ids = fetch_todays_games(session)
        assert any(g.id == future_game.id for g in games)

    def test_future_game_is_bettable(self, session, future_game):
        _, bettable_ids = fetch_todays_games(session)
        assert future_game.id in bettable_ids

    def test_past_game_not_bettable(self, session, past_game):
        _, bettable_ids = fetch_todays_games(session)
        assert past_game.id not in bettable_ids
