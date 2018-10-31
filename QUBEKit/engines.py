#!/usr/bin/env python


import helpers
import decs
from subprocess import call as sub_call


class Engines:
    """Engines superclass containing core information that all other engines (psi4, g09 etc) will have.
    Provides atoms' coordinates with name tags for each atom and entire molecule.
    Also gives all configs from the appropriate config file."""

    def __init__(self, molecule, config_file):
        # Obtains the molecule name and a list of elements in the molecule with their respective coordinates.
        self.molecule_name, self.molecule = helpers.pdb_to_coord_list(molecule)
        # Load the configs using the config_file name.
        confs = helpers.config_loader(config_file)
        self.qm, self.fitting, self.paths = confs

    # def __repr__(self):
    #     """Returns representation of the object"""
    #     return 'class: {}, args: ("{}")'.format(self.__class__.__name__, self.molecule_name.__name__)


class Parametrisation(Engines):
    """Class of functions which perform the initial parametrisation for the molecules."""

    def __init__(self, molecule, config_file):

        super().__init__(molecule, config_file)

    def antechamber(self):
        pass

    def openff(self):
        pass


@decs.for_all_methods(decs.timer_func)
class PSI4(Engines):
    """Psi4 class (child of Engines).
    Used to extract optimised structures, hessians, frequencies, etc.
    """

    def __init__(self, molecule, config_file, geometric, solvent):

        super().__init__(molecule, config_file)
        self.geometric = geometric
        # if not self.solvent, calculation will be in vacuo.
        self.solvent = solvent

    def hessian(self):
        """Parses the Hessian from the output.dat file (from psi4) into a numpy array.
        molecule is a numpy array of size N x N
        """

        from numpy import array

        hess_size = len(self.molecule) * 3
        # output.dat is the psi4 output file.
        with open('output.dat', 'r') as file:

            lines = file.readlines()

            for count, line in enumerate(lines):

                if '## Hessian' in line:
                    # Set the start of the hessian to the row of the first value.
                    start_of_hess = count + 5
                    # Set the end of the Hessian to the row of the last value (+1 to be sure).
                    end_of_hess = start_of_hess + hess_size * (hess_size // 5 + 1) + (hess_size // 5 - 1) * 4 + 1
                    hess_vals = []

                    for file_line in lines[start_of_hess:end_of_hess]:
                        # Compile lists of the 5 Hessian floats for each row.
                        # Number of floats in last row may be less than 5.
                        # Only the actual floats are added, not the separating numbers.
                        row_vals = [float(val) for val in file_line.split() if len(val) > 5]
                        hess_vals.append(row_vals)

                        # Removes blank list entries.
                        hess_vals = [elem for elem in hess_vals if elem]

                        # Currently, every list within hess_vals is a list of 5 floats.
                        # The lists need to be concatenated so that there are n=hess_size lists of m=hess_size length.
                        # This will give a matrix of size n x m as desired.

                    reshaped = []

                    for i in range(hess_size):
                        row = []
                        for j in range(hess_size // 5 + 1):
                            row += hess_vals[i + j * hess_size]

                        reshaped.append(row)

                    # Units conversion.
                    hess_matrix = array(reshaped) * 627.509391 / (0.529 ** 2)

                    print('Extracted Hessian for {} from psi4 output.'.format(self.molecule_name))

                    return hess_matrix

    def density(self):
        pass

    def optimised_structure(self):
        """Parses the final optimised structure from the output.dat file (from psi4) to a numpy array.
        """

        from numpy import array

        # Run through the file and find all lines containing '==> Geometry', add these lines to a list.
        # Reverse the list
        # from the start of this list, jump down to the first atom and set this as the start point
        # Split the row into 4 columns: centre, x, y, z.
        # Add each row to a matrix.
        # Return the matrix.

        # output.dat is the psi4 output file.
        with open('output.dat', 'r') as file:
            lines = file.readlines()
            geo_pos_list = []  # Will contain index of all the lines containing '==> Geometry'.
            for count, line in enumerate(lines):
                if "==> Geometry" in line:
                    geo_pos_list.append(count)

            # Set the start as the last instance of '==> Geometry'.
            start_of_vals = geo_pos_list[-1] + 9

            f_opt_struct = []

            for row in range(len(self.molecule)):

                # Append the first 4 columns of each row, converting to float as necessary.
                struct_row = [lines[start_of_vals + row].split()[0]]
                for indx in range(1, 4):
                    struct_row.append(float(lines[start_of_vals + row].split()[indx]))

                f_opt_struct.append(struct_row)
        print('Extracted optimised structure for {} from psi4 output.'.format(self.molecule_name))
        return array(f_opt_struct)

    def energy(self):
        pass

    def generate_input(self, charge, multiplicity):
        """Converts to psi4 input format to be run in psi4 without using geometric"""

        # input.dat is the psi4 input file.

        # TODO Change file name wrt analysis.

        with open('input.dat', 'w+') as input_file:
            input_file.write('memory {} GB\n\nmolecule {} {{\n{} {} \n'.format(self.qm['threads'], self.molecule_name,
                                                                               charge, multiplicity))

            for i in range(len(self.molecule)):
                input_file.write(' {}    {: .6f}  {: .6f}  {: .6f} \n'.format(self.molecule[i][0], float(self.molecule[i][1]),
                                                                        float(self.molecule[i][2]), float(self.molecule[i][3])))
            input_file.write('}}\n\nset basis {}'.format(self.qm['basis']))

            if not self.geometric:
                input_file.write("\noptimize('{}')".format(self.qm['theory'].lower()))
            input_file.write("\nenergy, wfn = frequency('{}', return_wfn=True)".format(self.qm['theory'].lower()))
            input_file.write('\nset hessian_write on\nwfn.hessian().print_out()\n\n')

            print('Setting chargemol parameters.')
            input_file.write("set cubeprop_tasks ['density']\n")

            # TODO Handle overage correctly (should be dependent on the size of the molecule)
            # See helpers.get_overage or bonds.get_overage for info.

            print('Calculating overage for psi4 and chargemol.')
            overage = helpers.get_overage(self.molecule_name)
            input_file.write("set CUBIC_GRID_OVERAGE [{0}, {0}, {0}]\n".format(overage))
            input_file.write("set CUBIC_GRID_SPACING [0.13, 0.13, 0.13]\n\n")
            input_file.write("grad, wfn = gradient('{}', return_wfn=True)\ncubeprop(wfn)".format(self.qm['theory'].lower()))

            if self.solvent:
                print('Setting pcm parameters.')
                input_file.write('\n\nset pcm true\nset pcm_scf_type total')
                input_file.write('\n\npcm = {')
                input_file.write('\n    units = Angstrom\n    Medium {\n    SolverType = IEFPCM\n    Solvent = Chloroform\n    }')
                input_file.write('\n    Cavity {\n    RadiiSet = UFF\n    Type = GePol\n    Scaling = False\n    Area = 0.3\n    Mode = Implicit')
                input_file.write('\n    }\n}')

        sub_call('psi4 input.dat -n {}'.format(self.qm['threads']), shell=True)

    def all_modes(self):

        from numpy import array

        # Find "post-proj  all modes"
        # Jump to first value, ignoring text.
        # Move through data, adding it to a list
        # continue onto next line.
        # Repeat until the following line is known to be empty.

        # output.dat is the psi4 output file.
        with open('output.dat', 'r') as file:
            lines = file.readlines()
            for count, line in enumerate(lines):
                if "post-proj  all modes" in line:
                    start_of_vals = count

                    # Barring the first (and sometimes last) line, dat file has 6 values per row.
                    end_of_vals = count + (3 * len(self.molecule)) // 6

                    structures = lines[start_of_vals][24:].replace("'", "").split()
                    structures = structures[6:]

                    for row in range(1, end_of_vals - start_of_vals):
                        # Remove double strings and weird formatting.
                        structures += lines[start_of_vals + row].replace("'", "").replace("]", "").split()

                    all_modes = [float(val) for val in structures]

                    return array(all_modes)


class Geometric(Engines):

    def __init__(self, molecule, config_file):

        super().__init__(molecule, config_file)

    def pdb_to_psi4_geo(self, charge, multiplicity):
        """Writes molecule data from pdb to psi4 input file.
        Also requires some default values such as basis and theory,
        and some values taken from the run prompt such as charge and multiplicity.
        """

        # TODO Allow alternative configs to be loaded.

        with open(self.molecule_name + '.psi4in', 'w+') as file:
            file.write('molecule {} {{\n {} {} \n'.format(self.molecule_name, charge, multiplicity))
            for i in range(len(self.molecule)):
                file.write('  {}    {: .6f}  {: .6f}  {: .6f}\n'.format(self.molecule[i][0], float(self.molecule[i][1]),
                                                                        float(self.molecule[i][2]), float(self.molecule[i][3])))

            file.write("}}\nset basis {}\ngradient('{}')".format(self.qm['basis'], self.qm['theory']))

        with open('log.txt', 'w+') as log:
            sub_call('geometric-optimize --psi4 {}.psi4in --nt {}'.format(self.molecule_name, self.qm['threads']),
                     shell=True, stdout=log)

    @staticmethod
    def optimised_structure():
        """Gets the optimised structure from psi4 ready to be used for the frequency.
        Option to change the location of the file for testing purposes."""

        opt_molecule = []
        write = False
        # opt.xyz is the geometric optimised structure file.
        with open('opt.xyz', 'r') as opt:
            lines = opt.readlines()
            for line in lines:
                if 'Iteration' in line:
                    print('Optimisation converged at iteration {} with final energy {}'.format(int(line.split()[1]), float(line.split()[3])))
                    write = True

                elif write:
                    opt_molecule.append([line.split()[0], float(line.split()[1]),
                                         float(line.split()[2]), float(line.split()[3])])

        return opt_molecule


class Chargemol(Engines):

    def __init__(self, molecule, config_file):

        super().__init__(molecule, config_file)

    def generate_input(self, chargemol_path, ddec_version=6):
        """Given a DDEC version (from the defaults), this function writes the job file for chargemol."""

        if ddec_version != 6 or ddec_version != 3:
            print('Invalid DDEC version given, running with default version 6.')
            ddec_version = 6

        # Write the charges job file.
        with open('job_control.txt', 'w+') as charge_file:

            charge_file.write('<net charge>\n0.0\n</net charge>')

            charge_file.write('\n\n<periodicity along A, B and C vectors>\n.false.\n.false.\n.false.')
            charge_file.write('\n</periodicity along A, B and C vectors>')

            charge_file.write('\n\n<atomic densities directory complete path>\n{}/atomic_densities/'.format(chargemol_path))
            charge_file.write('\n</atomic densities directory complete path>')

            charge_file.write('\n\n<charge type>\nDDEC{}\n</charge type>'.format(ddec_version))

            charge_file.write('\n\n<compute BOs>\n.true.\n</compute BOs>')

        sub_call('psi4 output.dat -n {}'.format(self.qm['threads']), shell=True)

        sub_call('mv Dt.cube total_density.cube', shell=True)
        sub_call(self.paths['chargemol'] + '/chargemol_FORTRAN_09_26_2017/compiled_binaries/linux/Chargemol_09_26_2017_linux_serial job_control.txt', shell=True)

    def extract_charges(self):
        """Extract the charge data from the chargemol execution."""

        pass
