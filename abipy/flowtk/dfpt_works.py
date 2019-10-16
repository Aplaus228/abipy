# coding: utf-8
"""Work subclasses related to DFTP."""

from .works import Work, MergeDdb


class ElasticWork(Work, MergeDdb):
    """
    This Work computes the elastic constants and (optionally) the piezoelectric tensor.
    It consists of Response function calculations for:

        * rigid-atom elastic tensor
        * rigid-atom piezoelectric tensor
        * interatomic force constants at gamma
        * Born effective charges

    The structure is assumed to be already relaxed

    Create a `Flow` for phonon calculations. The flow has one works with:

        - 1 GS Task
        - 3 DDK Task
        - 4 Phonon Tasks (Gamma point)
        - 6 Elastic tasks (3 uniaxial + 3 shear strain)

    The Phonon tasks and the elastic task will read the DDK produced at the beginning
    """
    @classmethod
    def from_scf_input(cls, scf_input, with_relaxed_ion=True, with_piezo=False, with_dde=False,
                       tolerances=None, den_deps=None, manager=None):
        """
        Args:
            scf_input:
            with_relaxed_ion:
            with_piezo:
            with_dde: Compute electric field perturbations.
            tolerances: Dict of tolerances
            den_deps:
            manager:

        Similar to `from_scf_task`, the difference is that this method requires
        an input for SCF calculation instead of a ScfTask. All the tasks (Scf + Phonon)
        are packed in a single Work whereas in the previous case we usually have multiple works.
        """
        if tolerances is None: tolerances = {}
        new = cls(manager=manager)

        # Register task for WFK0 calculation (either SCF or NCSCF if den_deps is given)
        if den_deps is None:
            wfk_task = new.register_scf_task(scf_input)
        else:
            tolwfr = 1.0e-20
            if "nscf" in tolerances:
                tolwfr = tolerances["nscf"]["tolwfr"]
            nscf_input = scf_input.new_with_vars(iscf=-2, tolwfr=tolwfr)
            wfk_task = new.register_nscf_task(nscf_input, deps=den_deps)

        if with_piezo or with_dde:
            # Calculate the ddk wf's needed for piezoelectric tensor and Born effective charges.
            #ddk_tolerance = {"tolwfr": 1.0e-20}
            ddk_tolerance = tolerances.get("ddk", None)
            ddk_multi = scf_input.make_ddk_inputs(tolerance=ddk_tolerance, manager=manager)
            ddk_tasks = []
            for inp in ddk_multi:
                ddk_task = new.register_ddk_task(inp, deps={wfk_task: "WFK"})
                ddk_tasks.append(ddk_task)
            ddk_deps = {ddk_task: "DDK" for ddk_task in ddk_tasks}

        if with_dde:
            # Add tasks for electric field perturbation.
            #dde_tolerance = None
            dde_tolerance = tolerances.get("dde", None)
            dde_multi = scf_input.make_dde_inputs(tolerance=dde_tolerance, use_symmetries=True, manager=manager)
            dde_deps = {wfk_task: "WFK"}
            dde_deps.update(ddk_deps)
            for inp in dde_multi:
                new.register_dde_task(inp, deps=dde_deps)

        # Build input files for strain and (optionally) phonons.
        #strain_tolerance = {"tolvrs": 1e-10}
        strain_tolerance = tolerances.get("strain", None)
        strain_multi = scf_input.make_strain_perts_inputs(tolerance=strain_tolerance, manager=manager,
            phonon_pert=with_relaxed_ion, kptopt=2)

        if with_relaxed_ion:
            # Phonon perturbation (read DDK if piezo).
            ph_deps = {wfk_task: "WFK"}
            if with_piezo: ph_deps.update(ddk_deps)
            for inp in strain_multi:
                if inp.get("rfphon", 0) == 1:
                    new.register_phonon_task(inp, deps=ph_deps)

        # Finally compute strain pertubations (read DDK if piezo).
        elast_deps = {wfk_task: "WFK"}
        if with_piezo: elast_deps.update(ddk_deps)
        for inp in strain_multi:
            if inp.get("rfstrs", 0) != 0:
                new.register_elastic_task(inp, deps=elast_deps)

        return new

    def on_all_ok(self):
        """
        This method is called when all the tasks of the Work reach S_OK.
        Ir runs `mrgddb` in sequential on the local machine to produce
        the final DDB file in the outdir of the `Work`.
        """
        # Merge DDB files.
        out_ddb = self.merge_ddb_files(delete_source_ddbs=False, only_dfpt_tasks=False)
        results = self.Results(node=self, returncode=0, message="DDB merge done")

        return results
