from __future__ import annotations

import unittest

import pandas as pd

from benchmarks import acumular_taxas_percentuais, acumular_variacoes_fechamento


class CalculoBenchmarksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.datas = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])

    def test_cdi_acumula_taxas_diarias_e_inicia_em_cem(self) -> None:
        taxas = pd.Series([0.10, 0.20, 0.30], index=self.datas)

        resultado = acumular_taxas_percentuais(taxas, "CDI")

        self.assertAlmostEqual(resultado.iloc[0], 100.0)
        self.assertAlmostEqual(resultado.iloc[-1], 100.0 * 1.002 * 1.003)

    def test_ibovespa_acumula_variacoes_do_close_e_inicia_em_cem(self) -> None:
        fechamentos = pd.Series([100_000.0, 102_000.0, 101_000.0], index=self.datas)

        resultado = acumular_variacoes_fechamento(fechamentos, "Ibovespa")

        self.assertAlmostEqual(resultado.iloc[0], 100.0)
        self.assertAlmostEqual(resultado.iloc[-1], 101.0)


if __name__ == "__main__":
    unittest.main()
