#!/usr/bin/env python
import unittest
import numpy

from pyscf import gto
from pyscf import scf
from pyscf import cc
from pyscf import ao2mo
from pyscf import fci

mol = gto.Mole()
mol.verbose = 0
mol.atom = [
    ['H', ( 1.,-1.    , 0.   )],
    ['H', ( 0.,-1.    ,-1.   )],
    ['H', ( 1.,-0.5   , 0.   )],
    ['H', ( 0.,-1.    , 1.   )],
]
mol.charge = 2
mol.basis = '3-21g'
mol.build()
mf = scf.RHF(mol).run()

def finger(a):
    return numpy.dot(a.ravel(), numpy.cos(numpy.arange(a.size)))

class KnownValues(unittest.TestCase):
    def test_ccsd(self):
        mycc = cc.CCSD(mf)
        ecc = mycc.kernel()[0]
        norb = mf.mo_coeff.shape[1]
        nelec = mol.nelec
        h2e = ao2mo.restore(1, ao2mo.kernel(mf._eri, mf.mo_coeff), norb)
        h1e = reduce(numpy.dot, (mf.mo_coeff.T, mf.get_hcore(), mf.mo_coeff))
        eci, civec = fci.direct_spin0.kernel(h1e, h2e, norb, nelec)
        dm1ref = fci.direct_spin0.make_rdm1(civec, norb, nelec)
        eci = eci + mol.energy_nuc() - mf.e_tot
        self.assertAlmostEqual(eci, ecc, 7)

        l1, l2 = mycc.solve_lambda()
        self.assertAlmostEqual(finger(l1), 0.0106196828089, 5)
        dm1 = mycc.make_rdm1()
        self.assertAlmostEqual(abs(dm1ref-dm1).max(), 0, 5)

if __name__ == "__main__":
    print("Full Tests for 2e CCSD")
    unittest.main()

