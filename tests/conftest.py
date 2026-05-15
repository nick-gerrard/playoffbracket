import pytest
from datetime import datetime, timedelta, timezone, date
from sqlmodel import SQLModel, Session, create_engine
from models import User, Season, Team, Series, Game, ScoringConfig, Bet, Prediction
from enums import BetStatus, GameStatus


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def user(session):
    u = User(name="Alice", email="alice@example.com", balance=1000)
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


@pytest.fixture
def other_user(session):
    u = User(name="Bob", email="bob@example.com", balance=1000)
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


@pytest.fixture
def season(session):
    s = Season(year=2026, picks_open=True)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


@pytest.fixture
def team_home(session):
    t = Team(api_id=1, name="Home Team", abbrev="HOM", logo_url="home.png", dark_logo_url="home_dark.png")
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


@pytest.fixture
def team_away(session):
    t = Team(api_id=2, name="Away Team", abbrev="AWY", logo_url="away.png", dark_logo_url="away_dark.png")
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


@pytest.fixture
def future_game(session, team_home, team_away):
    start = datetime.now(timezone.utc) + timedelta(hours=2)
    g = Game(
        api_id=100,
        date=datetime.now(timezone.utc).date(),
        start_time=start.replace(tzinfo=None),
        home_team=team_home.id,
        away_team=team_away.id,
        status=GameStatus.FUT,
    )
    session.add(g)
    session.commit()
    session.refresh(g)
    return g


@pytest.fixture
def past_game(session, team_home, team_away):
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    g = Game(
        api_id=101,
        date=yesterday,
        start_time=start.replace(tzinfo=None),
        home_team=team_home.id,
        away_team=team_away.id,
        status=GameStatus.OFF,
        winner=team_home.id,
    )
    session.add(g)
    session.commit()
    session.refresh(g)
    return g


@pytest.fixture
def series(session, season, team_home, team_away):
    s = Series(
        title="Series A",
        series_letter="A",
        series_abbrev="R1A",
        conference="East",
        playoff_round=1,
        season_id=season.id,
        top_seed_team=team_home.id,
        bottom_seed_team=team_away.id,
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


@pytest.fixture
def scoring(session, season):
    sc = ScoringConfig(season_year=season.year, series_abbrev="R1A", points=10)
    session.add(sc)
    session.commit()
    return sc


@pytest.fixture
def pending_bet(session, user, other_user, future_game, team_home):
    b = Bet(
        challenger=user.id,
        challengee=other_user.id,
        game_id=future_game.id,
        amount=100,
        challenger_winner=team_home.id,
        status=BetStatus.PENDING,
    )
    session.add(b)
    # escrow challenger's funds
    user.balance -= 100
    session.add(user)
    session.commit()
    session.refresh(b)
    session.refresh(user)
    return b
