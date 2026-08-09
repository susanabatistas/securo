from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.b3_import_service import aggregate_for_preview, parse_b3_csv

B3_CSV = """Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação
Credito;01/03/2026;Compra;PETR4 - PETROBRAS PN N2;XP INVESTIMENTOS;100;28,50;2850,00
Credito;15/03/2026;Compra;PETR4 - PETROBRAS PN N2;XP INVESTIMENTOS;50;30,00;1500,00
Debito;20/03/2026;Venda;PETR4 - PETROBRAS PN N2;XP INVESTIMENTOS;30;32,00;960,00
Credito;05/03/2026;Compra;HGLG11 - CSHG LOGISTICA FDO INV IMOB;XP INVESTIMENTOS;10;155,00;1550,00
Credito;10/03/2026;Dividendo;PETR4 - PETROBRAS PN N2;XP INVESTIMENTOS;100;;45,00
Credito;12/03/2026;Juros Sobre Capital Próprio;PETR4 - PETROBRAS PN N2;XP INVESTIMENTOS;100;;12,00
Credito;18/03/2026;Bonificação em Ativos;PETR4 - PETROBRAS PN N2;XP INVESTIMENTOS;5;;0,00
"""

# Real export from a Warren account (reported by a user): lowercase headers,
# lowercase movement labels, and numeric fields carry an embedded "R$"
# currency symbol + trailing space ("R$0,10 ") — parse_brl_decimal alone
# chokes on the "R$" prefix, which silently skipped every row as invalid
# before _clean_decimal_str was added.
WARREN_CSV = (
    "Entrada/Saída;data;movimentacao;produto;Instituição;quantidade;preco;valor\n"
    "Credito;30/06/2026;juros sobre capital proprio;"
    "CMIG4 - CIA. ENERGETICA DE MINAS GERAIS- CEMIG;WARREN;18;R$0,10 ;R$1,59 \n"
    "Credito;16/03/2026;dividendo;FIQE3 - UNIFIQUE TELECOMUNICAÇÕES S.A.;WARREN;24;R$0,08 ;R$1,86 \n"
    "Credito;13/03/2026;rendimento;BTHF11 - BTG PACTUAL REAL ESTATE HEDGE FUND FII - RESP LTDA;WARREN;22;R$0,10 ;R$2,22 \n"
)


def test_parse_b3_csv_handles_warren_currency_symbol_format():
    result = parse_b3_csv(WARREN_CSV.encode("utf-8"))
    assert result.skipped_count == 0
    assert len(result.income_rows) == 3

    jcp = next(r for r in result.income_rows if r.ticker == "CMIG4.SA")
    assert jcp.kind == "jcp"
    assert jcp.amount == Decimal("1.59")
    assert jcp.date == date(2026, 6, 30)

    dividendo = next(r for r in result.income_rows if r.ticker == "FIQE3.SA")
    assert dividendo.kind == "dividendo"
    assert dividendo.amount == Decimal("1.86")

    rendimento = next(r for r in result.income_rows if r.ticker == "BTHF11.SA")
    assert rendimento.kind == "rendimento"
    assert rendimento.amount == Decimal("2.22")


def test_parse_b3_csv_filters_to_compra_venda_only():
    result = parse_b3_csv(B3_CSV.encode("utf-8"))
    assert len(result.rows) == 4
    assert {r.kind for r in result.rows} == {"buy", "sell"}
    # Dividendo/JCP become income rows now, not skipped — only Bonificação
    # (no monetary value to record) is genuinely ignored.
    assert result.skipped_count == 1
    assert result.skipped_kinds.get("Bonificação em Ativos") == 1


def test_parse_b3_csv_recognizes_income_rows():
    result = parse_b3_csv(B3_CSV.encode("utf-8"))
    assert len(result.income_rows) == 2
    kinds = {r.kind for r in result.income_rows}
    assert kinds == {"dividendo", "jcp"}

    dividendo = next(r for r in result.income_rows if r.kind == "dividendo")
    assert dividendo.ticker == "PETR4.SA"
    assert dividendo.amount == Decimal("45.00")
    assert dividendo.date == date(2026, 3, 10)

    jcp = next(r for r in result.income_rows if r.kind == "jcp")
    assert jcp.amount == Decimal("12.00")


def test_parse_b3_csv_extracts_ticker_and_fields():
    result = parse_b3_csv(B3_CSV.encode("utf-8"))
    petr4_buy = next(r for r in result.rows if r.ticker == "PETR4.SA" and r.kind == "buy" and r.quantity == Decimal("100"))
    assert petr4_buy.price == Decimal("28.50")
    assert petr4_buy.date == date(2026, 3, 1)

    hglg = next(r for r in result.rows if r.ticker == "HGLG11.SA")
    assert hglg.kind == "buy"
    assert hglg.quantity == Decimal("10")
    assert hglg.price == Decimal("155.00")


def test_parse_b3_csv_derives_price_from_operation_value_when_unit_price_missing():
    csv_text = (
        "Movimentação;Data;Produto;Quantidade;Valor da Operação\n"
        "Compra;01/03/2026;VALE3 - VALE ON;10;600,00\n"
    )
    result = parse_b3_csv(csv_text.encode("utf-8"))
    assert len(result.rows) == 1
    assert result.rows[0].price == Decimal("60.000000")


def test_parse_b3_csv_raises_clear_error_on_unrecognized_format():
    garbage = "col_a,col_b\n1,2\n"
    with pytest.raises(ValueError, match="não reconhecido"):
        parse_b3_csv(garbage.encode("utf-8"))


def test_parse_b3_csv_raises_on_empty_file():
    with pytest.raises(ValueError):
        parse_b3_csv(b"")


def test_parse_b3_csv_skips_malformed_row_without_failing_whole_import():
    csv_text = (
        "Movimentação;Data;Produto;Quantidade;Preço unitário\n"
        "Compra;01/03/2026;PETR4 - PETROBRAS PN N2;100;28,50\n"
        "Compra;not-a-date;VALE3 - VALE ON;10;60,00\n"
    )
    result = parse_b3_csv(csv_text.encode("utf-8"))
    assert len(result.rows) == 1
    assert result.skipped_count == 1


def test_parse_b3_csv_tolerates_column_name_variations():
    # Different casing/accents/column order than the canonical header.
    csv_text = (
        "PRODUTO,DATA,TIPO DE MOVIMENTACAO,QUANTIDADE,PRECO UNITARIO\n"
        "PETR4 - PETROBRAS PN N2,01/03/2026,COMPRA,100,28.50\n"
    )
    result = parse_b3_csv(csv_text.encode("utf-8"))
    assert len(result.rows) == 1
    assert result.rows[0].ticker == "PETR4.SA"


def test_aggregate_for_preview_weighted_average_and_date_range():
    result = parse_b3_csv(B3_CSV.encode("utf-8"))
    previews = aggregate_for_preview(result.rows)
    petr4 = next(p for p in previews if p.ticker == "PETR4.SA")
    # (100*28.50 + 50*30.00) / 150 = 29.00
    assert petr4.buy_quantity == Decimal("150")
    assert petr4.buy_average_price == Decimal("29.000000")
    assert petr4.sell_quantity == Decimal("30")
    assert petr4.sell_average_price == Decimal("32.000000")
    assert petr4.first_date == date(2026, 3, 1)
    assert petr4.last_date == date(2026, 3, 20)
    assert petr4.row_count == 3

    hglg = next(p for p in previews if p.ticker == "HGLG11.SA")
    assert hglg.buy_quantity == Decimal("10")
    assert hglg.sell_quantity == Decimal("0")
