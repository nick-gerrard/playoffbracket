import pytest
import main
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.pool import StaticPool
from unittest.mock import patch, MagicMock
from models import User, Season, Bet, Prediction
from enums import BetStatus


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def admin_user(engine):
    with Session(engine) as session:
        u = User(name="Admin", email="admin@example.com", balance=1000)
        session.add(u)
        session.commit()
        session.refresh(u)
        return u


@pytest.fixture
def regular_user(engine):
    with Session(engine) as session:
        u = User(name="Regular", email="regular@example.com", balance=500)
        session.add(u)
        session.commit()
        session.refresh(u)
        return u


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setattr(main, "engine", engine)
    main.ADMIN_EMAIL = "admin@example.com"
    with patch("main.get_series_data", return_value=[]), \
         patch("main.get_team_stats_data", return_value=[]), \
         patch("main.seed_season", return_value=MagicMock(id=1)), \
         patch("main.seed_teams"), \
         patch("main.seed_series"), \
         patch("main.seed_scoring_config"), \
         patch("main.seed_standings_data"), \
         patch("main.ingest_games"), \
         patch.object(main.scheduler, "start"), \
         patch.object(main.scheduler, "shutdown"):
        SQLModel.metadata.create_all(engine)
        with TestClient(main.app, raise_server_exceptions=True) as c:
            yield c


@pytest.fixture
def auth_client(client, regular_user):
    from main import get_current_user
    main.app.dependency_overrides[get_current_user] = lambda: regular_user
    yield client
    main.app.dependency_overrides.clear()


@pytest.fixture
def admin_client(client, admin_user):
    from main import get_current_user
    main.app.dependency_overrides[get_current_user] = lambda: admin_user
    yield client
    main.app.dependency_overrides.clear()


# --- Auth ---

class TestAuth:
    def test_root_redirects_unauthenticated(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "/login" in resp.headers["location"]

    def test_login_page_renders(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_logout_clears_session(self, auth_client):
        resp = auth_client.get("/logout", follow_redirects=False)
        assert resp.status_code in (302, 307)


# --- Bracket ---

class TestBracketRoutes:
    def test_bracket_redirects_unauthenticated(self, client):
        resp = client.get("/bracket", follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_bracket_redirects_to_predict_when_no_predictions(self, auth_client, engine):
        with Session(engine) as session:
            s = Season(year=2026, picks_open=True)
            session.add(s)
            session.commit()
        resp = auth_client.get("/bracket", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "/predict" in resp.headers["location"]

    def test_predict_redirects_when_picks_closed(self, auth_client, engine):
        with Session(engine) as session:
            s = Season(year=2026, picks_open=False)
            session.add(s)
            session.commit()
        resp = auth_client.get("/predict", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert resp.headers["location"] == "/"


# --- Leaderboard ---

class TestLeaderboard:
    def test_leaderboard_redirects_unauthenticated(self, client):
        resp = client.get("/leaderboard", follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_leaderboard_renders(self, auth_client, engine):
        with Session(engine) as session:
            s = Season(year=2026)
            session.add(s)
            session.commit()
        resp = auth_client.get("/leaderboard")
        assert resp.status_code == 200


# --- Vault ---

class TestVault:
    def test_vault_redirects_unauthenticated(self, client):
        resp = client.get("/vault", follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_vault_renders(self, auth_client):
        resp = auth_client.get("/vault")
        assert resp.status_code == 200


# --- Bets ---

class TestBetsRoutes:
    def test_bets_redirects_unauthenticated(self, client):
        resp = client.get("/bets", follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_bets_page_renders(self, auth_client):
        resp = auth_client.get("/bets")
        assert resp.status_code == 200

    def test_decline_bet_redirects(self, auth_client, engine, regular_user):
        from models import Team, Game, Bet
        from datetime import datetime, timedelta, timezone
        with Session(engine) as session:
            home = Team(api_id=10, name="Home", abbrev="HOM", logo_url="", dark_logo_url="")
            away = Team(api_id=11, name="Away", abbrev="AWY", logo_url="", dark_logo_url="")
            session.add(home)
            session.add(away)
            session.commit()
            session.refresh(home)
            session.refresh(away)
            start = datetime.now(timezone.utc) + timedelta(hours=2)
            game = Game(api_id=200, date=start.date(), start_time=start.replace(tzinfo=None),
                        home_team=home.id, away_team=away.id)
            session.add(game)
            challenger = User(name="Challenger", email="challenger@example.com", balance=500)
            session.add(challenger)
            session.commit()
            session.refresh(game)
            session.refresh(challenger)
            bet = Bet(challenger=challenger.id, challengee=regular_user.id,
                      game_id=game.id, amount=50, challenger_winner=home.id,
                      status=BetStatus.PENDING)
            session.add(bet)
            session.commit()
            session.refresh(bet)
            bet_id = bet.id
        resp = auth_client.post(f"/bets/decline/{bet_id}", follow_redirects=False)
        assert resp.status_code in (302, 303, 307)


# --- Admin ---

class TestAdminRoutes:
    def test_admin_forbidden_for_non_admin(self, auth_client):
        resp = auth_client.get("/admin")
        assert resp.status_code == 403

    def test_admin_renders_for_admin(self, admin_client, engine):
        with Session(engine) as session:
            s = Season(year=2026)
            session.add(s)
            session.commit()
        resp = admin_client.get("/admin")
        assert resp.status_code == 200

    def test_toggle_picks_flips_state(self, admin_client, engine):
        with Session(engine) as session:
            s = Season(year=2026, picks_open=True)
            session.add(s)
            session.commit()
        admin_client.post("/admin/toggle-picks")
        with Session(engine) as session:
            s = session.exec(select(Season)).first()
            assert s.picks_open is False

    def test_admin_credit(self, admin_client, engine, regular_user):
        initial = regular_user.balance
        admin_client.post("/admin/credit", data={
            "user_id": regular_user.id,
            "amount": 100,
            "desc": "test credit",
        })
        with Session(engine) as session:
            u = session.get(User, regular_user.id)
            assert u.balance == initial + 100


# --- About ---

class TestAbout:
    def test_about_renders_unauthenticated(self, client):
        resp = client.get("/about")
        assert resp.status_code == 200
