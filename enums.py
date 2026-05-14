from enum import StrEnum


class BetStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class GameStatus(StrEnum):
    FUT = "FUT"
    OFF = "OFF"


class GameOutcome(StrEnum):
    REG = "REG"
    OT = "OT"


class SeriesRound(StrEnum):
    R1 = "R1"
    R2 = "R2"
    ECF = "ECF"
    WCF = "WCF"
    SCF = "SCF"


class TransactionKind(StrEnum):
    SIGNUP_BONUS = "signup_bonus"
    BET_ESCROW = "bet_escrow"
    BET_WIN = "bet_win"
    BET_REFUND = "bet_refund"
    ADMIN_CREDIT = "admin_credit"
    BRACKET_BONUS = "bracket_bonus"
