#!/usr/bin/env python
#
# Author: Qiming Sun <osirpt.sun@gmail.com>
#

import numpy
from pyscf import lib
from pyscf import gto
from pyscf import df

'''
QM part interface
'''

def mm_charge(method, coords, charges):
    '''Modify the QM method using the potential generated by MM charges.

    Args:
        method : a HF/DFT/MCSCF/MP2/CCSD ... object

        coords : 2D array, shape (N,3)
            MM particle coordinates
        charges : 1D array
            MM particle charges

    Returns:
        Same method object as the input method with modified 1e Hamiltonian

    Note:
        1. if MM charge and X2C correction are used together, function mm_charge
        needs to be applied after X2C decoration (scf.sfx2c function), eg
        mf = mm_charge(scf.sfx2c(scf.RHF(mol)), [(0.5,0.6,0.8)], [-0.5]).
        2. Once mm_charge function is applied on the "method" object, it affects
        all following calculations eg MP2, CCSD, MCSCF etc

    Examples:

    >>> mol = gto.M(atom='H 0 0 0; F 0 0 1', basis='ccpvdz', verbose=0)
    >>> mf = mm_charge(dft.RKS(mol), [(0.5,0.6,0.8)], [-0.3])
    >>> mf.kernel()
    -101.940495711284
    '''
    coords = numpy.asarray(coords, order='C')
    charges = numpy.asarray(charges)

    class QMMM(method.__class__):
        def __init__(self):
            self.__dict__.update(method.__dict__)

        def get_hcore(self, mol=None):
            if hasattr(method, 'get_hcore'):
                h1e = method.get_hcore(mol)
            else:  # post-HF objects
                h1e = method._scf.get_hcore(mol)

            if 0: # For debug
                v = 0
                for i,q in enumerate(charges):
                    mol.set_rinv_origin_(coords[i])
                    v += mol.intor('cint1e_rinv_sph') * q
            else:
                fakemol = _make_fakemol(coords)
                j3c = df.incore.aux_e2(mol, fakemol, intor='cint3c2e_sph', aosym='s2ij')
                v = lib.unpack_tril(numpy.einsum('xk,k->x', j3c, charges))
            return h1e + v

    return QMMM()

def mm_charge_grad(method, coords, charges):
    '''Apply the MM charges in the QM gradients' method.  It affects both the
    electronic and nuclear parts of the QM fragment.

    Args:
        method : a HF or DFT gradient object (grad.HF or grad.RKS etc)
            Once mm_charge_grad function is applied on the "method" object, it
            affects all following calculations eg MP2, CCSD, MCSCF etc
        coords : 2D array, shape (N,3)
            MM particle coordinates
        charges : 1D array
            MM particle charges

    Returns:
        Same gradeints method object as the input method

    Examples:

    >>> from pyscf import gto, scf, grad
    >>> mol = gto.M(atom='H 0 0 0; F 0 0 1', basis='ccpvdz', verbose=0)
    >>> mf = mm_charge(scf.RHF(mol), [(0.5,0.6,0.8)], [-0.3])
    >>> mf.kernel()
    -101.940495711284
    >>> hfg = mm_charge_grad(grad.hf.RHF(mf), coords, charges)
    >>> hfg.kernel()
    [[-0.25912357 -0.29235976 -0.38245077]
     [-1.70497052 -1.89423883  1.2794798 ]]
    '''
    coords = numpy.asarray(coords, order='C')
    charges = numpy.asarray(charges)

    class QMMM(method.__class__):
        def __init__(self):
            self.__dict__.update(method.__dict__)

        def get_hcore(self, mol=None):
            ''' (QM 1e grad) + <-d/dX i|q_mm/r_mm|j>'''
            if mol is None: mol = method.mol
            g_qm = method.get_hcore(mol)
            nao = g_qm.shape[1]
            if 0: # For debug
                v = 0
                for i,q in enumerate(charges):
                    mol.set_rinv_origin_(coords[i])
                    v += mol.intor('cint1e_iprinv_sph') * q
            else:
                fakemol = _make_fakemol(coords)
                j3c = df.incore.aux_e2(mol, fakemol, intor='cint3c2e_ip1_sph',
                                       aosym='s1', comp=3)
                v = numpy.einsum('ixk,k->ix', j3c, charges).reshape(3,nao,nao)
            return method.get_hcore(mol) - v

        def grad_nuc(self, mol=None, atmlst=None):
            if mol is None: mol = method.mol
            g_qm = method.grad_nuc(mol, atmlst)
            g_mm = numpy.empty((mol.natm,3))
            for i in range(mol.natm):
                q1 = mol.atom_charge(i)
                r1 = mol.atom_coord(i)
                r = lib.norm(r1-coords, axis=1)
                g_mm[i] = -q1 * numpy.einsum('i,ix,i->x', charges, r1-coords, 1/r**3)
            if atmlst is not None:
                g_mm = g_mm[atmlst]
            return g_qm + g_mm
    return QMMM()

def _make_fakemol(coords):
    nbas = coords.shape[0]
    fakeatm = numpy.zeros((nbas,gto.ATM_SLOTS), dtype=numpy.int32)
    fakebas = numpy.zeros((nbas,gto.BAS_SLOTS), dtype=numpy.int32)
    fakeenv = []
    ptr = 0
    fakeatm[:,gto.PTR_COORD] = numpy.arange(0, nbas*3, 3)
    fakeenv.append(coords.ravel())
    ptr += nbas*3
    fakebas[:,gto.ATOM_OF] = numpy.arange(nbas)
    fakebas[:,gto.NPRIM_OF] = 1
    fakebas[:,gto.NCTR_OF] = 1
# approximate point charge with gaussian distribution exp(-1e9*r^2)
    fakebas[:,gto.PTR_EXP] = ptr
    fakebas[:,gto.PTR_COEFF] = ptr+1
    expnt = 1e9
    fakeenv.append([expnt, 1/(2*numpy.sqrt(numpy.pi)*gto.mole._gaussian_int(2,expnt))])
    ptr += 2
    fakemol = gto.Mole()
    fakemol._atm = fakeatm
    fakemol._bas = fakebas
    fakemol._env = numpy.hstack(fakeenv)
    fakemol.natm = nbas
    fakemol.nbas = nbas
    fakemol._built = True
    return fakemol

if __name__ == '__main__':
    from pyscf import scf, cc, grad
    mol = gto.Mole()
    mol.atom = ''' O                  0.00000000    0.00000000   -0.11081188
                   H                 -0.00000000   -0.84695236    0.59109389
                   H                 -0.00000000    0.89830571    0.52404783 '''
    mol.basis = 'cc-pvdz'
    mol.build()

    coords = [(0.5,0.6,0.8)]
    #coords = [(0.0,0.0,0.0)]
    charges = [-0.5]
    mf = mm_charge(scf.RHF(mol), coords, charges)
    print mf.kernel() # -79.5603900667
    mycc = cc.ccsd.CCSD(mf)
    mycc.conv_tol = 1e-10
    mycc.conv_tol_normt = 1e-10
    ecc, t1, t2 = mycc.kernel() # ecc = -0.214974249975
    l1, l2 = mycc.solve_lambda()[1:]

    hfg = mm_charge_grad(grad.hf.RHF(mf), coords, charges)
    g1 = grad.ccsd.kernel(mycc, t1, t2, l1, l2, grad_hf=hfg)
    print(g1 + hfg.grad_nuc(mol))
# [[-1.70176287 -1.8007835  -2.62867229]
#  [-0.02869778 -0.11235647  0.0073083 ]
#  [-0.19963132  0.15760018 -0.06471946]]

