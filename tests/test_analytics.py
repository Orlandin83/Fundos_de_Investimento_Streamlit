from __future__ import annotations

import unittest

import pandas as pd

from analytics import retorno_acumulado_base_100


class RetornoAcumuladoTest(unittest.TestCase):
    def test_converte_base_cem_em_percentual_decimal(self) -> None:
        base_100 = pd.Series([100.0, 125.0, 185.0])

        retorno = retorno_acumulado_base_100(base_100)

        for observado, esperado in zip(retorno, [0.0, 0.25, 0.85], strict=True):
            self.assertAlmostEqual(observado, esperado)


if __name__ == "__main__":
    unittest.main()
