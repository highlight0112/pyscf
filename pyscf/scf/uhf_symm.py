#!/usr/bin/env python
#
# Author: Qiming Sun <osirpt.sun@gmail.com>
#

'''
Non-relativistic unrestricted Hartree-Fock with point group symmetry.
'''

from functools import reduce
import numpy
import scipy.linalg
from pyscf import lib
from pyscf import symm
from pyscf.lib import logger
from pyscf.scf import hf_symm
from pyscf.scf import uhf
from pyscf.scf import chkfile


def analyze(mf, verbose=logger.DEBUG, **kwargs):
    from pyscf.lo import orth
    from pyscf.tools import dump_mat
    mol = mf.mol
    if not mol.symmetry:
        return uhf.analyze(mf, verbose, **kwargs)

    mo_energy = mf.mo_energy
    mo_occ = mf.mo_occ
    mo_coeff = mf.mo_coeff
    ovlp_ao = mf.get_ovlp()
    log = logger.new_logger(mf, verbose)
    if log.verbose >= logger.NOTE:
        nirrep = len(mol.irrep_id)
        ovlp_ao = mf.get_ovlp()
        orbsyma, orbsymb = get_orbsym(mf.mol, mo_coeff, ovlp_ao, False)
        tot_sym = 0
        noccsa = [sum(orbsyma[mo_occ[0]>0]==ir) for ir in mol.irrep_id]
        noccsb = [sum(orbsymb[mo_occ[1]>0]==ir) for ir in mol.irrep_id]
        for i, ir in enumerate(mol.irrep_id):
            if (noccsa[i]+noccsb[i]) % 2:
                tot_sym ^= ir
        if mol.groupname in ('Dooh', 'Coov', 'SO3'):
            log.note('TODO: total symmetry for %s', mol.groupname)
        else:
            log.note('total symmetry = %s',
                     symm.irrep_id2name(mol.groupname, tot_sym))
        log.note('alpha occupancy for each irrep:  '+(' %4s'*nirrep),
                 *mol.irrep_name)
        log.note('                                 '+(' %4d'*nirrep),
                 *noccsa)
        log.note('beta  occupancy for each irrep:  '+(' %4s'*nirrep),
                 *mol.irrep_name)
        log.note('                                 '+(' %4d'*nirrep),
                 *noccsb)

        log.note('**** MO energy ****')
        irname_full = {}
        for k, ir in enumerate(mol.irrep_id):
            irname_full[ir] = mol.irrep_name[k]
        irorbcnt = {}
        for k, j in enumerate(orbsyma):
            if j in irorbcnt:
                irorbcnt[j] += 1
            else:
                irorbcnt[j] = 1
            log.note('alpha MO #%d (%s #%d), energy= %.15g occ= %g',
                     k+1, irname_full[j], irorbcnt[j], mo_energy[0][k], mo_occ[0][k])
        irorbcnt = {}
        for k, j in enumerate(orbsymb):
            if j in irorbcnt:
                irorbcnt[j] += 1
            else:
                irorbcnt[j] = 1
            log.note('beta  MO #%d (%s #%d), energy= %.15g occ= %g',
                     k+1, irname_full[j], irorbcnt[j], mo_energy[1][k], mo_occ[1][k])

    if mf.verbose >= logger.DEBUG:
        label = mol.ao_labels()
        molabel = []
        irorbcnt = {}
        for k, j in enumerate(orbsyma):
            if j in irorbcnt:
                irorbcnt[j] += 1
            else:
                irorbcnt[j] = 1
            molabel.append('#%-d(%s #%d)' % (k+1, irname_full[j], irorbcnt[j]))
        log.debug(' ** alpha MO coefficients (expansion on meta-Lowdin AOs) **')
        orth_coeff = orth.orth_ao(mol, 'meta_lowdin', s=ovlp_ao)
        c_inv = numpy.dot(orth_coeff.T, ovlp_ao)
        dump_mat.dump_rec(mol.stdout, c_inv.dot(mo_coeff[0]), label, molabel,
                          start=1, **kwargs)

        molabel = []
        irorbcnt = {}
        for k, j in enumerate(orbsymb):
            if j in irorbcnt:
                irorbcnt[j] += 1
            else:
                irorbcnt[j] = 1
            molabel.append('#%-d(%s #%d)' % (k+1, irname_full[j], irorbcnt[j]))
        log.debug(' ** beta MO coefficients (expansion on meta-Lowdin AOs) **')
        dump_mat.dump_rec(mol.stdout, c_inv.dot(mo_coeff[1]), label, molabel,
                          start=1, **kwargs)

    dm = mf.make_rdm1(mo_coeff, mo_occ)
    return mf.mulliken_meta(mol, dm, s=ovlp_ao, verbose=log)

def get_irrep_nelec(mol, mo_coeff, mo_occ, s=None):
    '''Alpha/beta electron numbers for each irreducible representation.

    Args:
        mol : an instance of :class:`Mole`
            To provide irrep_id, and spin-adapted basis
        mo_occ : a list of 1D ndarray
            Regular occupancy, without grouping for irreps
        mo_coeff : a list of 2D ndarray
            Regular orbital coefficients, without grouping for irreps

    Returns:
        irrep_nelec : dict
            The number of alpha/beta electrons for each irrep {'ir_name':(int,int), ...}.

    Examples:

    >>> mol = gto.M(atom='O 0 0 0; H 0 0 1; H 0 1 0', basis='ccpvdz', symmetry=True, charge=1, spin=1, verbose=0)
    >>> mf = scf.UHF(mol)
    >>> mf.scf()
    -75.623975516256721
    >>> scf.uhf_symm.get_irrep_nelec(mol, mf.mo_coeff, mf.mo_occ)
    {'A1': (3, 3), 'A2': (0, 0), 'B1': (1, 1), 'B2': (1, 0)}
    '''
    if hasattr(mo_coeff[0], 'orbsym'):
        orbsyma = mo_coeff[0].orbsym
    else:
        orbsyma = symm.label_orb_symm(mol, mol.irrep_id, mol.symm_orb,
                                      mo_coeff[0], s, False)
    if hasattr(mo_coeff[1], 'orbsym'):
        orbsymb = mo_coeff[1].orbsym
    else:
        orbsymb = symm.label_orb_symm(mol, mol.irrep_id, mol.symm_orb,
                                      mo_coeff[1], s, False)
    orbsyma = numpy.array(orbsyma)
    orbsymb = numpy.array(orbsymb)
    irrep_nelec = dict([(mol.irrep_name[k], (int(sum(mo_occ[0][orbsyma==ir])),
                                             int(sum(mo_occ[1][orbsymb==ir]))))
                        for k, ir in enumerate(mol.irrep_id)])
    return irrep_nelec

rhf_to_uhf = uhf.rhf_to_uhf

def canonicalize(mf, mo_coeff, mo_occ, fock=None):
    '''Canonicalization diagonalizes the UHF Fock matrix in occupied, virtual
    subspaces separatedly (without change occupancy).
    '''
    mol = mf.mol
    if not mol.symmetry:
        return uhf.canonicalize(mf, mo_coeff, mo_occ, fock)

    mo_occ = numpy.asarray(mo_occ)
    assert(mo_occ.ndim == 2)
    if fock is None:
        dm = mf.make_rdm1(mo_coeff, mo_occ)
        fock = mf.get_hcore() + mf.get_veff(mf.mol, dm)
    occidxa = mo_occ[0] == 1
    occidxb = mo_occ[1] == 1
    viridxa = ~occidxa
    viridxb = ~occidxb
    mo = numpy.empty_like(mo_coeff)
    mo_e = numpy.empty(mo_occ.shape)

    if (hasattr(mo_coeff, 'orbsym') or
        (hasattr(mo_coeff[0], 'orbsym') and hasattr(mo_coeff[1], 'orbsym'))):
        orbsyma, orbsymb = get_orbsym(mol, mo_coeff)
        def eig_(fock, mo_coeff, idx, es, cs):
            if numpy.count_nonzero(idx) > 0:
                orb = mo_coeff[:,idx]
                f1 = reduce(numpy.dot, (orb.T.conj(), fock, orb))
                e, c = scipy.linalg.eigh(f1)
                es[idx] = e
                cs[:,idx] = numpy.dot(mo_coeff[:,idx], c)

        for ir in set(orbsyma):
            idx_ir = orbsyma == ir
            eig_(fock[0], mo_coeff[0], idx_ir & occidxa, mo_e[0], mo[0])
            eig_(fock[0], mo_coeff[0], idx_ir & viridxa, mo_e[0], mo[0])
        for ir in set(orbsymb):
            idx_ir = orbsymb == ir
            eig_(fock[1], mo_coeff[1], idx_ir & occidxb, mo_e[1], mo[1])
            eig_(fock[1], mo_coeff[1], idx_ir & viridxb, mo_e[1], mo[1])

    else:
        s = mf.get_ovlp()
        def eig_(fock, mo_coeff, idx, es, cs):
            if numpy.count_nonzero(idx) > 0:
                orb = mo_coeff[:,idx]
                f1 = reduce(numpy.dot, (orb.T.conj(), fock, orb))
                e, c = scipy.linalg.eigh(f1)
                es[idx] = e
                c = numpy.dot(mo_coeff[:,idx], c)
                cs[:,idx] = hf_symm._symmetrize_canonicalization_(mf, e, c, s)

        eig_(fock[0], mo_coeff[0], occidxa, mo_e[0], mo[0])
        eig_(fock[0], mo_coeff[0], viridxa, mo_e[0], mo[0])
        eig_(fock[1], mo_coeff[1], occidxb, mo_e[1], mo[1])
        eig_(fock[1], mo_coeff[1], viridxb, mo_e[1], mo[1])
        orbsyma, orbsymb = get_orbsym(mol, mo, s, False)

    mo = hf_symm.attach_orbsym(mo, (orbsyma,orbsymb))
    return mo_e, mo


class UHF(uhf.UHF):
    __doc__ = uhf.UHF.__doc__ + '''
    Attributes for symmetry allowed UHF:
        irrep_nelec : dict
            Specify the number of alpha/beta electrons for particular irrep
            {'ir_name':(int,int), ...}.
            For the irreps not listed in these dicts, the program will choose the
            occupancy based on the orbital energies.

    Examples:

    >>> mol = gto.M(atom='O 0 0 0; H 0 0 1; H 0 1 0', basis='ccpvdz', symmetry=True, charge=1, spin=1, verbose=0)
    >>> mf = scf.RHF(mol)
    >>> mf.scf()
    -75.623975516256692
    >>> mf.get_irrep_nelec()
    {'A1': (3, 3), 'A2': (0, 0), 'B1': (1, 1), 'B2': (1, 0)}
    >>> mf.irrep_nelec = {'B1': (1, 0)}
    >>> mf.scf()
    -75.429189192031131
    >>> mf.get_irrep_nelec()
    {'A1': (3, 3), 'A2': (0, 0), 'B1': (1, 0), 'B2': (1, 1)}
    '''
    def __init__(self, mol):
        uhf.UHF.__init__(self, mol)
        # number of electrons for each irreps
        self.irrep_nelec = {}
        self._keys = self._keys.union(['irrep_nelec'])

    def dump_flags(self):
        uhf.UHF.dump_flags(self)
        if self.irrep_nelec:
            logger.info(self, 'irrep_nelec %s', self.irrep_nelec)
        return self

    def build(self, mol=None):
        if mol is None: mol = self.mol
        if mol.symmetry:
            hf_symm.check_irrep_nelec(mol, self.irrep_nelec, self.nelec)
        return uhf.UHF.build(self, mol)

    def eig(self, h, s):
        mol = self.mol
        if not mol.symmetry:
            return self._eigh(h, s)

        nirrep = mol.symm_orb.__len__()
        s = symm.symmetrize_matrix(s, mol.symm_orb)
        ha = symm.symmetrize_matrix(h[0], mol.symm_orb)
        cs = []
        es = []
        orbsym = []
        for ir in range(nirrep):
            e, c = self._eigh(ha[ir], s[ir])
            cs.append(c)
            es.append(e)
            orbsym.append([mol.irrep_id[ir]] * e.size)
        ea = numpy.hstack(es)
        ca = hf_symm.so2ao_mo_coeff(mol.symm_orb, cs)
        ca = hf_symm.attach_orbsym(ca, numpy.hstack(orbsym))

        hb = symm.symmetrize_matrix(h[1], mol.symm_orb)
        cs = []
        es = []
        orbsym = []
        for ir in range(nirrep):
            e, c = self._eigh(hb[ir], s[ir])
            cs.append(c)
            es.append(e)
            orbsym.append([mol.irrep_id[ir]] * e.size)
        eb = numpy.hstack(es)
        cb = hf_symm.so2ao_mo_coeff(mol.symm_orb, cs)
        cb = hf_symm.attach_orbsym(cb, numpy.hstack(orbsym))
        return numpy.array((ea,eb)), (ca,cb)

    def get_grad(self, mo_coeff, mo_occ, fock=None):
        g = uhf.UHF.get_grad(self, mo_coeff, mo_occ, fock)
        if self.mol.symmetry:
            occidxa = mo_occ[0] > 0
            occidxb = mo_occ[1] > 0
            viridxa = ~occidxa
            viridxb = ~occidxb
            orbsyma, orbsymb = get_orbsym(self.mol, mo_coeff)
            sym_forbida = orbsyma[viridxa].reshape(-1,1) != orbsyma[occidxa]
            sym_forbidb = orbsymb[viridxb].reshape(-1,1) != orbsymb[occidxb]
            sym_forbid = numpy.hstack((sym_forbida.ravel(),
                                       sym_forbidb.ravel()))
            g[sym_forbid] = 0
        return g

    def get_occ(self, mo_energy=None, mo_coeff=None):
        ''' We assumed mo_energy are grouped by symmetry irreps, (see function
        self.eig). The orbitals are sorted after SCF.
        '''
        if mo_energy is None: mo_energy = self.mo_energy
        mol = self.mol
        if not mol.symmetry:
            return uhf.UHF.get_occ(self, mo_energy, mo_coeff)

        orbsyma, orbsymb = get_orbsym(mol, mo_coeff)

        mo_occ = numpy.zeros_like(mo_energy)
        idx_ea_left = []
        idx_eb_left = []
        neleca_fix = nelecb_fix = 0
        for i, ir in enumerate(mol.irrep_id):
            irname = mol.irrep_name[i]
            ir_idxa = numpy.where(orbsyma == ir)[0]
            ir_idxb = numpy.where(orbsymb == ir)[0]
            if irname in self.irrep_nelec:
                if isinstance(self.irrep_nelec[irname], (int, numpy.integer)):
                    nelecb = self.irrep_nelec[irname] // 2
                    neleca = self.irrep_nelec[irname] - nelecb
                else:
                    neleca, nelecb = self.irrep_nelec[irname]
                ea_idx = numpy.argsort(mo_energy[0][ir_idxa].round(9))
                eb_idx = numpy.argsort(mo_energy[1][ir_idxb].round(9))
                mo_occ[0,ir_idxa[ea_idx[:neleca]]] = 1
                mo_occ[1,ir_idxb[eb_idx[:nelecb]]] = 1
                neleca_fix += neleca
                nelecb_fix += nelecb
            else:
                idx_ea_left.append(ir_idxa)
                idx_eb_left.append(ir_idxb)

        neleca_float = self.nelec[0] - neleca_fix
        nelecb_float = self.nelec[1] - nelecb_fix
        assert(neleca_float >= 0)
        assert(nelecb_float >= 0)
        if len(idx_ea_left) > 0:
            idx_ea_left = numpy.hstack(idx_ea_left)
            ea_left = mo_energy[0][idx_ea_left]
            ea_sort = numpy.argsort(ea_left.round(9))
            occ_idx = idx_ea_left[ea_sort][:neleca_float]
            mo_occ[0][occ_idx] = 1
        if len(idx_eb_left) > 0:
            idx_eb_left = numpy.hstack(idx_eb_left)
            eb_left = mo_energy[1][idx_eb_left]
            eb_sort = numpy.argsort(eb_left.round(9))
            occ_idx = idx_eb_left[eb_sort][:nelecb_float]
            mo_occ[1][occ_idx] = 1

        vir_idx = (mo_occ[0]==0)
        if self.verbose >= logger.INFO and numpy.count_nonzero(vir_idx) > 0:
            noccsa = []
            noccsb = []
            p0 = 0
            for i, ir in enumerate(mol.irrep_id):
                irname = mol.irrep_name[i]
                ir_idxa = orbsyma == ir
                ir_idxb = orbsymb == ir
                noccsa.append(numpy.count_nonzero(mo_occ[0][ir_idxa]))
                noccsb.append(numpy.count_nonzero(mo_occ[1][ir_idxb]))

            ir_id2name = dict(zip(mol.irrep_id, mol.irrep_name))
            ehomo = ehomoa = max(mo_energy[0][mo_occ[0]>0 ])
            elumo = elumoa = min(mo_energy[0][mo_occ[0]==0])
            irhomoa = ir_id2name[orbsyma[mo_energy[0] == ehomoa][0]]
            irlumoa = ir_id2name[orbsyma[mo_energy[0] == elumoa][0]]
            logger.info(self, 'alpha HOMO (%s) = %.15g  LUMO (%s) = %.15g',
                        irhomoa, ehomoa, irlumoa, elumoa)
            if nelecb_float > 0:
                ehomob = max(mo_energy[1][mo_occ[1]>0 ])
                elumob = min(mo_energy[1][mo_occ[1]==0])
                irhomob = ir_id2name[orbsymb[mo_energy[1] == ehomob][0]]
                irlumob = ir_id2name[orbsymb[mo_energy[1] == elumob][0]]
                logger.info(self, 'beta  HOMO (%s) = %.15g  LUMO (%s) = %.15g',
                            irhomob, ehomob, irlumob, elumob)
                ehomo = max(ehomoa,ehomob)
                elumo = min(elumoa,elumob)

            logger.debug(self, 'alpha irrep_nelec = %s', noccsa)
            logger.debug(self, 'beta  irrep_nelec = %s', noccsb)
            hf_symm._dump_mo_energy(mol, mo_energy[0], mo_occ[0], ehomo, elumo,
                                    orbsyma, 'alpha-', verbose=self.verbose)
            hf_symm._dump_mo_energy(mol, mo_energy[1], mo_occ[1], ehomo, elumo,
                                    orbsymb, 'beta-', verbose=self.verbose)

            if mo_coeff is not None and self.verbose >= logger.DEBUG:
                ovlp_ao = self.get_ovlp()
                ss, s = self.spin_square((mo_coeff[0][:,mo_occ[0]>0],
                                          mo_coeff[1][:,mo_occ[1]>0]), ovlp_ao)
                logger.debug(self, 'multiplicity <S^2> = %.8g  2S+1 = %.8g', ss, s)
        return mo_occ

    def _finalize(self):
        uhf.UHF._finalize(self)

        ea = numpy.hstack(self.mo_energy[0])
        eb = numpy.hstack(self.mo_energy[1])
        oa_sort = numpy.argsort(ea[self.mo_occ[0]>0 ].round(9))
        va_sort = numpy.argsort(ea[self.mo_occ[0]==0].round(9))
        ob_sort = numpy.argsort(eb[self.mo_occ[1]>0 ].round(9))
        vb_sort = numpy.argsort(eb[self.mo_occ[1]==0].round(9))
        self.mo_energy = (numpy.hstack((ea[self.mo_occ[0]>0 ][oa_sort],
                                        ea[self.mo_occ[0]==0][va_sort])),
                          numpy.hstack((eb[self.mo_occ[1]>0 ][ob_sort],
                                        eb[self.mo_occ[1]==0][vb_sort])))
        ca = self.mo_coeff[0]
        cb = self.mo_coeff[1]
        self.mo_coeff = (numpy.hstack((ca[:,self.mo_occ[0]>0 ].take(oa_sort, axis=1),
                                       ca[:,self.mo_occ[0]==0].take(va_sort, axis=1))),
                         numpy.hstack((cb[:,self.mo_occ[1]>0 ].take(ob_sort, axis=1),
                                       cb[:,self.mo_occ[1]==0].take(vb_sort, axis=1))))
        nocc_a = int(self.mo_occ[0].sum())
        nocc_b = int(self.mo_occ[1].sum())
        self.mo_occ[0][:nocc_a] = 1
        self.mo_occ[0][nocc_a:] = 0
        self.mo_occ[1][:nocc_b] = 1
        self.mo_occ[1][nocc_b:] = 0
        if self.chkfile:
            chkfile.dump_scf(self.mol, self.chkfile, self.e_tot, self.mo_energy,
                             self.mo_coeff, self.mo_occ, overwrite_mol=True)
        return self

    def analyze(self, verbose=None, **kwargs):
        if verbose is None: verbose = self.verbose
        return analyze(self, verbose, **kwargs)

    @lib.with_doc(get_irrep_nelec.__doc__)
    def get_irrep_nelec(self, mol=None, mo_coeff=None, mo_occ=None, s=None):
        if mol is None: mol = self.mol
        if mo_occ is None: mo_occ = self.mo_occ
        if mo_coeff is None: mo_coeff = self.mo_coeff
        if s is None: s = self.get_ovlp()
        return get_irrep_nelec(mol, mo_coeff, mo_occ, s)

    canonicalize = canonicalize

def get_orbsym(mol, mo_coeff, s=None, check=False):
    if hasattr(mo_coeff, 'orbsym'):
        orbsym = mo_coeff.orbsym
    else:
        orbsym = (hf_symm.get_orbsym(mol, mo_coeff[0], s, check),
                  hf_symm.get_orbsym(mol, mo_coeff[1], s, check))
    return numpy.asarray(orbsym)

class HF1e(UHF):
    def scf(self, *args):
        logger.info(self, '\n')
        logger.info(self, '******** 1 electron system ********')
        self.converged = True
        h1e = self.get_hcore(self.mol)
        s1e = self.get_ovlp(self.mol)
        self.mo_energy, self.mo_coeff = self.eig([h1e]*2, s1e)
        self.mo_occ = self.get_occ(self.mo_energy, self.mo_coeff)
        self.e_tot = self.mo_energy[0][self.mo_occ[0]>0][0] + self.mol.energy_nuc()
        self._finalize()
        return self.e_tot


if __name__ == '__main__':
    from pyscf import gto
    mol = gto.Mole()
    mol.build(
        verbose = 1,
        output = None,
        atom = [['H', (0.,0.,0.)],
                ['H', (0.,0.,1.)], ],
        basis = {'H': 'ccpvdz'},
        symmetry = True,
        charge = -1,
        spin = 1
    )

    method = UHF(mol)
    method.verbose = 5
    method.irrep_nelec['A1u'] = (1,0)
    energy = method.kernel()
    print(energy)
    method.analyze()