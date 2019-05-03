"""
Submodule with classes and utilities to deal with and parse .dec decay files.

Basic assumptions
-----------------

1) For standard (non-alias) particle (names):
    - Decay modes defined via a 'Decay' statement.
    - Related antiparticle decay modes either defined via a 'CDecay' statement
      or via a 'Decay' statement. The latter option is often used if CP matters.
2) For particle names defined via aliases:
    - Particle decay modes defined as above.
    - Related antiparticle decay modes defined with either options above,
      *but* there needs to be a 'ChargeConj' statement specifying the
      particle-antiparticle match. Typically::

        Alias MyP+ P+
        Alias MyP- P-
        ChargeConj MyP+ MyP-
        Decay MyP+
        ...
        Enddecay
        CDecay MyP-

3) As a consequence, particles that are self-conjugate should not be used
   in 'CDecay' statements, obviously.
"""

from __future__ import absolute_import, division, print_function

import os
import warnings

from lark import Lark
from lark import Tree, Transformer, Visitor

from particle import Particle, ParticleNotFound

from ..data import open_text
from .. import data
from ..decay.decay import Decay
from .enums import PhotosEnum


# New in Python 3
try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError


class DecFileNotParsed(RuntimeError):
    pass


class DecayNotFound(RuntimeError):
    pass


class DecFileParser(object):
    """
    The class to parse a .dec decay file.

    Example
    -------
    >>> parsed_file = DecFileParser.from_file('my-decay-file.dec')
    """

    __slots__ = ("_grammar",
                 "_grammar_info",
                 "_dec_file_name",
                 "_parsed_dec_file",
                 "_parsed_decays",
                 "_include_ccdecays")

    def __init__(self, filename):
        """
        Default constructor.

        Parameters
        ----------
        filename: str
            Input .dec decay file name.
        """
        self._grammar = None       # Loaded Lark grammar definition file
        self._grammar_info = None  # Name of Lark grammar definition file

        # Conversion to handle pathlib on Python < 3.6:
        self._dec_file_name = str(filename)  # Name of the input decay file
        self._parsed_dec_file = None      # Parsed decay file

        self._parsed_decays = None  # Particle decays found in the decay file

        # By default, consider charge-conjugate decays when parsing
        self._include_ccdecays = True

    @classmethod
    def from_file(cls, filename):
        """
        Parse a .dec decay file.

        Parameters
        ----------
        filename: str
            Input .dec decay file name.
        """
        # Conversion to handle pathlib on Python < 3.6:
        filename = str(filename)

        # Check input file
        if not os.path.exists(filename):
            raise FileNotFoundError("'{0}'!".format(filename))

        return cls(filename)

    def parse(self, include_ccdecays=True):
        """
        Parse the given .dec decay file according to default Lark parser
        and specified options, i.e.,
            parser = 'lalr',
            lexer = 'standard'.

        See method 'load_grammar' for how to explicitly define the grammar
        and set the Lark parsing options.

        Parameters
        ----------
        include_ccdecays: boolean, optional, default=True
            Choose whether or not to consider charge-conjugate decays,
            which are specified via "CDecay <MOTHER>".
            Make sure you understand the consequences of ignoring
            charge conjugate decays - you won't have a complete picture!
        """
        # Has a file been parsed already?
        if self._parsed_decays is not None:
            warnings.warn("Input file being re-parsed ...")

        # Override the parsing settings for charge conjugate decays
        self._include_ccdecays = include_ccdecays if include_ccdecays else False

        # Retrieve all info on the default Lark grammar and its default options,
        # effectively loading it
        opts = self.grammar_info()
        extraopts = dict((k, v) for k, v in opts.items()
                         if k not in ('lark_file', 'parser','lexer'))

        # Instantiate the Lark parser according to chosen settings
        parser = Lark(self.grammar(), parser=opts['parser'], lexer=opts['lexer'])

        dec_file = open(self._dec_file_name).read()
        self._parsed_dec_file = parser.parse(dec_file)

        # At last, find all particle decays defined in the .dec decay file ...
        self._find_parsed_decays()

        # ... and create on the fly the charge conjugate decays, if requested
        if self._include_ccdecays:
            self._add_charge_conjugate_decays()

    def grammar(self):
        """
        Access the internal Lark grammar definition file,
        loading it from the default location if needed.

        Returns
        -------
        out: str
            The Lark grammar definition file.
        """
        if not self.grammar_loaded:
            self.load_grammar()

        return self._grammar

    def grammar_info(self):
        """
        Access the internal Lark grammar definition file name and
        parser options, loading the grammar from the default location if needed.

        Returns
        -------
        out: dict
            The Lark grammar definition file name and parser options.
        """
        if not self.grammar_loaded:
            self.load_grammar()

        return self._grammar_info

    def load_grammar(self, filename=None, parser='lalr', lexer='standard', **options):
        """
        Load a Lark grammar definition file, either the default one,
        or a user-specified one, optionally setting Lark parsing options.

        Parameters
        ----------
        filename: str, optional, default=None
            Input .dec decay file name. By default 'data/decfile.lark' is loaded.
        parser: str, optional, default='lalr'
            The Lark parser engine name.
        lexer: str, optional, default='standard'
            The Lark parser lexer mode to use.
        options: keyword arguments, optional
            Extra options to pass on to the parsing algorithm.

        See Lark's Lark class for a description of available options
        for parser, lexer and options.
        """

        if filename is None:
            filename = 'decfile.lark'
            with data.open_text(data, filename) as f:
                self._grammar = f.read()
        else:
            # Conversion to handle pathlib on Python < 3.6:
            filename = str(filename)

            self._grammar = open(filename).read()

        self._grammar_info = dict(lark_file=filename, parser=parser, lexer=lexer, **options)

    @property
    def grammar_loaded(self):
        """Check to see if the Lark grammar definition file is loaded."""
        return self._grammar is not None

    def dict_definitions(self):
        """
        Return a dictionary of all definitions in the input parsed file,
        of the form "Define <NAME> <VALUE>",
        as {'NAME1': VALUE1, 'NAME2': VALUE2, ...}.
        """
        return get_definitions(self._parsed_dec_file)

    def dict_aliases(self):
        """
        Return a dictionary of all alias definitions in the input parsed file,
        of the form "Alias <NAME> <ALIAS>",
        as {'NAME1': ALIAS1, 'NAME2': ALIAS2, ...}.
        """
        return get_aliases(self._parsed_dec_file)

    def dict_charge_conjugates(self):
        """
        Return a dictionary of all charge conjugate definitions
        in the input parsed file, of the form
        "ChargeConj <PARTICLE> <CC_PARTICLE>", as
        {'PARTICLE1': CC_PARTICLE1, 'PARTICLE2': CC_PARTICLE2, ...}.
        """
        return get_charge_conjugate_defs(self._parsed_dec_file)

    def dict_pythia_definitions(self):
        """
        Return a dictionary of all Pythia definitions in the input parsed file,
        of the form
        "PythiaBothParam <NAME>=<LABEL>"
        or
        "PythiaBothParam <NAME>=<NUMBER>",
        as {'NAME1': 'LABEL1', 'NAME2': VALUE2, ...}.
        """
        return get_pythia_definitions(self._parsed_dec_file)

    def list_lineshape_definitions(self):
        """
        Return a dictionary of all SetLineshapePW definitions in the input parsed file,
        of the form
        "SetLineshapePW <MOTHER> <DAUGHTER1> <DAUGHTER2> <VALUE>",
        as
        [(['MOTHER1', 'DAUGHTER1-1', 'DAUGHTER1-2'], VALUE1),
        (['MOTHER2', 'DAUGHTER2-1', 'DAUGHTER2-2'], VALUE2),
        ...]
        """
        return get_lineshape_definitions(self._parsed_dec_file)

    def global_photos_flag(self):
        """
        Return a boolean-like PhotosEnum enum specifying whether or not PHOTOS
        has been enabled.

        Note: PHOTOS is turned on(off) for all decays with the global flag
        yesPhotos(noPhotos).

        Returns
        -------
        out: PhotosEnum, default=PhotosEnum.no
            PhotosEnum.yes / PhotosEnum.no if PHOTOS enabled / disabled
        """
        return get_global_photos_flag(self._parsed_dec_file)

    def list_charge_conjugate_decays(self):
        """
        Return a (sorted) list of all charge conjugate decay definitions
        in the input parsed file, of the form "CDecay <MOTHER>", as
        ['MOTHER1', 'MOTHER2', ...].
        """
        return get_charge_conjugate_decays(self._parsed_dec_file)

    def _find_parsed_decays(self):
        """
        Return a tuple of all decay definitions in the input parsed file,
        of the form
        "Decay <MOTHER>",
        as a tuple of Lark Tree instances with Tree.data=='decay', i.e.,
        (Tree(decay, [Tree(particle, [Token(LABEL, <MOTHER1>]), ...),
        Tree(decay, [Tree(particle, [Token(LABEL, <MOTHER2>]), ...)).

        Duplicate definitions (a bug, of course) are removed, issuing a warning.

        Note
        ----
        1) Method not meant to be used directly!
        2) charge conjugates need to be dealt with differently,
        see 'self._add_charge_conjugate_decays()'.
        """
        if self._parsed_dec_file is not None:
            self._parsed_decays = get_decays(self._parsed_dec_file)

        # Check for duplicates - should be considered a bug in the .dec file!
        self._check_parsed_decays()

    def _add_charge_conjugate_decays(self):
        """
        If requested (see the 'self._include_ccdecays' class attribute),
        create the Lark Tree instances describing the charge conjugate decays
        specified in the input parsed file via the statements of the form
        "CDecay <MOTHER>".
        These are added to the internal list of decays stored in the class
        in variable 'self._parsed_decays', performing a charge conjugate (CC)
        transformation on each CC-related decay, which is cloned.

        Note
        ----
        1) If a decay file only defines 'Decay' decays and no 'CDecay',
        then no charge conjugate decays will be created!
        This seems correct given the "instructions" in the decay file:
        - There is no 'CDecay' statement related to a 'Decay' statement
          for a self-conjugate decaying particle such as the pi0.
        - Else the decay file should be considered incomplete, hence buggy.
        2) Method not meant to be used directly!
        """

        # Do not add any charge conjugate decays if the input parsed file
        # does not define any!
        mother_names_ccdecays = self.list_charge_conjugate_decays()
        if len(mother_names_ccdecays) == 0:
            return

        # Cross-check - make sure charge conjugate decays are not defined
        # with both 'Decay' and 'CDecay' statements!
        mother_names_decays = [get_decay_mother_name(tree)
                               for tree in self._parsed_decays]

        duplicates = [n for n in mother_names_ccdecays if n in mother_names_decays]
        if len(duplicates) > 0:
            msg = """The following particles are defined in the input .dec file with both 'Decay' and 'CDecay': {0}!
The 'CDecay' definition(s) will be ignored ...""".format(', '.join(d for d in duplicates))
            warnings.warn(msg)

        # If that's the case, proceed using the decay definitions specified
        # via the 'Decay' statement, hence discard/remove the definition
        # via the 'CDecay' statement.
        for d in duplicates:
            mother_names_ccdecays.remove(d)

        # We're done if there are no more 'CDecay' decays to treat!
        if len(mother_names_ccdecays) == 0:
            return

        # At last, create the charge conjugate decays:
        # First, make a (deep) copy of the list of relevant Tree instances.
        # Example:
        # if mother_names_ccdecays = ['anti-M1', 'anti-M2'],
        # the relevant Trees are the ones describing the decays of ['M1', 'M2'].
        dict_cc_names = self.dict_charge_conjugates()

        i = 0
        trees_to_conjugate = []
        for ccname in mother_names_ccdecays:
            name = find_charge_conjugate_match(ccname, dict_cc_names)
            i += 1
            match = list(self._parsed_dec_file.find_pred(
                lambda t: t.data=='decay' and t.children[0].children[0].value == name))
            trees_to_conjugate.extend(match)

        cdecays = [ tree.__deepcopy__(None) for tree in trees_to_conjugate]

        # Finally, perform all particle -> anti(particle) replacements,
        # taking care of charge conjugate decays defined via aliases,
        # passing them as charge conjugates to be processed manually.
        [ChargeConjugateReplacement(charge_conj_defs=dict_cc_names).visit(t)
        for t in cdecays]

        # ... and add all these charge-conjugate decays to the list of decays!
        self._parsed_decays.extend(cdecays)

    def _check_parsing(self):
        """Has the .parse() method been called already?"""
        if self._parsed_dec_file is None:
            raise DecFileNotParsed("Hint: call 'parse()'!")

    def _check_parsed_decays(self):
        """
        Is the number of decays parsed consistent with the number of
        decay mother names? An inconsistency can arise if decays are redefined.

        Duplicates are removed, starting from the second occurrence.
        """
        # Issue a helpful warning if duplicates are found
        lmn = self.list_decay_mother_names()
        duplicates = []
        if self.number_of_decays != len(set(lmn)):
            duplicates = set([n for n in lmn if lmn.count(n)>1])
            msg = """The following particle(s) is(are) redefined in the input .dec file with 'Decay': {0}!
All but the first occurrence will be discarded/removed ...""".format(', '.join(d for d in duplicates))
            warnings.warn(msg)

        # Create a list with all occurrences to remove
        # (duplications means multiple instances to remove)
        duplicates_to_remove = []
        for item in duplicates:
            c = lmn.count(item)
            if c>1:
                duplicates_to_remove.extend([item]*(c-1))

        # Actually remove all but the first occurrence of duplicate decays
        for tree in reversed(self._parsed_decays):
            val = tree.children[0].children[0].value
            if val in duplicates_to_remove:
                duplicates_to_remove.remove(val)
                self._parsed_decays.remove(tree)

    @property
    def number_of_decays(self):
        """Return the number of particle decays defined in the parsed .dec file."""
        self._check_parsing()

        return len(self._parsed_decays)

    def list_decay_mother_names(self):
        """
        Return a list of all decay mother names found in the parsed decay file.
        """
        self._check_parsing()

        return [get_decay_mother_name(d) for d in self._parsed_decays]

    def _find_decay_modes(self, mother):
        """
        Return a tuple of Lark Tree instances describing all the decay modes
        of the input mother particle as defined in the parsed .dec file.

        Parameters
        ----------
        mother: str
            Input mother particle name.
        """
        self._check_parsing()

        for decay_Tree in self._parsed_decays:
            if get_decay_mother_name(decay_Tree) == mother:
                return tuple(decay_Tree.find_data('decayline'))

        raise DecayNotFound("Decays of particle '%s' not found in .dec file!" % mother)

    def list_decay_modes(self, mother):
        """
        Return a list of decay modes for the given mother particle.

        Example
        -------
        >>> parser = DecFileParser('my-decay-file.dec')
        >>> parser.parse()
        >>> parser.list_decay_mother_names()  # Inspect what decays are defined
        >>> parser.list_decay_modes('pi0')
        """
        return [get_final_state_particle_names(mode)
                for mode in self._find_decay_modes(mother)]

    def _decay_mode_details(self, decay_mode):
        """
        Parse a decay mode (Tree instance)
        and return the relevant bits of information in it.
        """

        bf = get_branching_fraction(decay_mode)
        fsp_names = get_final_state_particle_names(decay_mode)
        model = get_model_name(decay_mode)
        model_params = get_model_parameters(decay_mode)

        return (bf, fsp_names, model, model_params)

    def print_decay_modes(self, mother):
        """Pretty print (debugging) of the decay modes of a given particle."""
        dms = self._find_decay_modes(mother)

        for dm in dms:
            dm_details = self._decay_mode_details(dm)
            print('%12g : %50s %15s %s' % (dm_details[0], '  '.\
                join(p for p in dm_details[1]), dm_details[2], dm_details[3]))

    def build_decay_chain(self, mother, stable_particles=[]):
        """
        Iteratively build the whole decay chain of a given mother particle,
        optionally considering certain particles as stable.

        Parameters
        ----------
        mother: str
            Input mother particle name.
        stable_particles: iterable, optional, default=[]
            If provided, stops the decay-chain parsing, taking the "list" as particles to be considered stable.

        Returns
        -------
        out: dict
            Decay chain as a dictionary of the form
            {mother: [{'bf': float, 'fs': list, 'm': str, 'mp': str}]}
            where
            'bf' stands for the deca mode branching fraction,
            'fs' is a list of final-state particle names (strings)
            and/or dictionaries of the same form as the decay chain above,
            'm' is the model name, if found, else '',
            'mp' are the model parameters, if specified, else ''

        Examples
        --------
        >>> parser = DecFileParser('a-Dplus-decay-file.dec')
        >>> parser.parse()
        >>> parser.build_decay_chain('D+')
        {'D+': [{'bf': 1.0,
           'fs': ['K-',
            'pi+',
            'pi+',
            {'pi0': [{'bf': 0.988228297,
               'fs': ['gamma', 'gamma'],
               'm': 'PHSP',
               'mp': ''},
              {'bf': 0.011738247,
               'fs': ['e+', 'e-', 'gamma'],
               'm': 'PI0_DALITZ',
               'mp': ''},
              {'bf': 3.3392e-05,
              'fs': ['e+', 'e+', 'e-', 'e-'],
              'm': 'PHSP',
              'mp': ''},
              {'bf': 6.5e-08, 'fs': ['e+', 'e-'], 'm': 'PHSP', 'mp': ''}]}],
           'm': 'PHSP',
           'mp': ''}]}
        >>> p.build_decay_chain('D+', stable_particles=['pi0'])
        {'D+': [{'bf': 1.0, 'fs': ['K-', 'pi+', 'pi+', 'pi0'], 'm': 'PHSP', 'mp': ''}]}
        """
        keys = ('bf', 'fs', 'm', 'mp')

        info = list()
        for dm in (self._find_decay_modes(mother)):
            list_dm_details = self._decay_mode_details(dm)
            d = dict(zip(keys,list_dm_details))

            for i, fs in enumerate(d['fs']):
                if fs in stable_particles:
                    continue

                try:
                    # This throws a DecayNotFound exception
                    # if fs does not have decays defined in the parsed file
                    _n_dms = len(self._find_decay_modes(fs))

                    _info = self.build_decay_chain(fs, stable_particles)
                    d['fs'][i] = _info
                except DecayNotFound:
                    pass

            info.append(d)

        info = {mother:info}
        return info

    def __repr__(self):
        if self._parsed_dec_file is not None:
            return "<{self.__class__.__name__}: decfile='{decfile}', n_decays={n_decays}>".format(
                self=self, decfile=self._dec_file_name, n_decays=self.number_of_decays)
        else:
            return "<{self.__class__.__name__}: decfile='{decfile}'>"\
                    .format(self=self, decfile=self._dec_file_name)

    def __str__(self):
        return repr(self)


class ChargeConjugateReplacement(Visitor):
    """
    Lark Visitor implementing the replacement of all particle names
    with their charge conjugate particle names
    in a Lark Tree of name 'particle' (Tree.data == 'particle').

    Note
    ----
    1) There is no check of whether the mother particle is self-conjugate or not.
    It is the responsibility of the caller to make sure the operation
    is not trivial, meaning returning the same (self-conjugate) decay!
    2) If a particle name (say, 'UNKOWN') is not found or known,
    (search done via the Particle class in the particle package),
    its charge conjugate name is denoted as 'ChargeConj(UNKOWN)'.

    Parameters
    ----------
    charge_conj_defs: dict, optional, default={}
        Dictionary with the charge conjugate particle definitions
        in the parsed file. Argument to be passed to the class constructor.

    Examples
    --------
    >>> from lark import Tree, Token
    >>> ...
    >>> t = Tree('decay', [Tree('particle', [Token('LABEL', 'D0')]), Tree('decayline', [Tree
    ... ('value', [Token('SIGNED_NUMBER', '1.0')]), Tree('particle', [Token('LABEL', 'K-')])
    ... , Tree('particle', [Token('LABEL', 'pi+')]), Tree('model', [Token('MODEL_NAME', 'PHS
    ... P')])])])
    >>> ChargeConjugateReplacement().visit(t)
    Tree(decay, [Tree(particle, [Token(LABEL, 'D~0')]), Tree(decayline,
    [Tree(value, [Token(SIGNED_NUMBER, '1.0')]), Tree(particle, [Token(LABEL, 'K+')]),
    Tree(particle, [Token(LABEL, 'pi-')]), Tree(model, [Token(MODEL_NAME, 'PHSP')])])])
    """
    def __init__(self, charge_conj_defs=dict()):
        self.charge_conj_defs = charge_conj_defs

    # TODO: this can be improved!
    def _last_chance_matching(self, pname):
        try:
            return Particle.from_dec(pname).invert().name
        except ParticleNotFound:
            return 'ChargeConj({0})'.format(pname)

    def particle(self, tree):
        """
        Method for the rule (here, a replacement) we wish to implement.
        """
        assert tree.data == 'particle'
        pname = tree.children[0].value
        if len(self.charge_conj_defs) > 0:
            for p, ccp in self.charge_conj_defs.items():
                if ccp == pname:
                    tree.children[0].value = p
                # Yes, both 'ChargeConj P CCP' and 'ChargeConj CCP P' are relevant
                elif p == pname:
                    tree.children[0].value = ccp
                else:
                    tree.children[0].value = self._last_chance_matching(tree.children[0].value)
        else:
            tree.children[0].value = self._last_chance_matching(tree.children[0].value)


def find_charge_conjugate_match(ccname, dict_cc_names=dict()):
    # TODO: this can be improved! To be revisited ...
    if len(dict_cc_names) > 0:
        for p, ccp in dict_cc_names.items():
            if ccp == ccname:
                return p
            # Yes, both 'ChargeConj P CCP' and 'ChargeConj CCP P' are relevant
            elif p == ccname:
                return ccp
        else:
            try:
                return Particle.from_dec(ccname).invert().name
            except ParticleNotFound:
                return 'ChargeConj({0})'.format(ccname)
    else:
        try:
            return Particle.from_dec(ccname).invert().name
        except ParticleNotFound:
            return 'ChargeConj({0})'.format(ccname)


def get_decay_mother_name(decay_tree):
    """
    Return the mother particle name for the decay mode defined
    in the input Tree of name 'decay'.

    Parameters
    ----------
    decay_tree: Lark Tree instance
        Input Tree satisfying Tree.data=='decay'.
    """
    if not isinstance(decay_tree, Tree) or decay_tree.data != 'decay':
        raise RuntimeError("Input not an instance of a 'decay' Tree!")

    # For a 'decay' Tree, tree.children[0] is the mother particle Tree
    # and tree.children[0].children[0].value is the mother particle name
    return decay_tree.children[0].children[0].value


def get_branching_fraction(decay_mode):
    """
    Return the branching fraction (float) for the decay mode defined
    in the input Tree of name 'decayline'.

    Parameters
    ----------
    decay_mode: Lark Tree instance
        Input Tree satisfying Tree.data=='decayline'.
    """
    if not isinstance(decay_mode, Tree) or decay_mode.data != 'decayline':
        raise RuntimeError("Check your input, not an instance of a 'decayline' Tree!")

    # For a 'decayline' Tree, Tree.children[0] is the branching fraction Tree
    # and tree.children[0].children[0].value is the BF stored as a str
    try:  # the branching fraction value as a float
        return float(decay_mode.children[0].children[0].value)
    except RuntimeError:
        raise RuntimeError("'decayline' Tree does not seem to have the usual structure. Check it.")


def get_final_state_particles(decay_mode):
    """
    Return a list of Lark Tree instances describing the final-state particles
    for the decay mode defined in the input Tree of name 'decayline'.

    Parameters
    ----------
    decay_mode: Lark Tree instance
        Input Tree satisfying Tree.data=='decayline'.

    Examples
    --------
    For a decay
        Decay MyB_s0
            1.000     K+     K-     SSD_CP 20.e12 0.1 1.0 0.04 9.6 -0.8 8.4 -0.6;
        Enddecay
    the list
        [Tree(particle, [Token(LABEL, 'K+')]), Tree(particle, [Token(LABEL, 'K-')])]
    will be returned.
    """
    if not isinstance(decay_mode, Tree) or decay_mode.data != 'decayline':
        raise RuntimeError("Input not an instance of a 'decayline' Tree!")

    # list of Trees of final-state particles
    return list(decay_mode.find_data('particle'))


def get_final_state_particle_names(decay_mode):
    """
    Return a list of final-state particle names for the decay mode defined
    in the input Tree of name 'decayline'.

    Parameters
    ----------
    decay_mode: Lark Tree instance
        Input Tree satisfying Tree.data=='decayline'.

    Examples
    --------
    For a decay
        Decay MyB_s0
            1.000     K+     K-     SSD_CP 20.e12 0.1 1.0 0.04 9.6 -0.8 8.4 -0.6;
        Enddecay
    the list ['K+', 'K-'] will be returned.
    """
    if not isinstance(decay_mode, Tree) or decay_mode.data != 'decayline':
        raise RuntimeError("Input not an instance of a 'decayline' Tree!")

    fsps = get_final_state_particles(decay_mode)
    # list of final-state particle names
    return [fsp.children[0].value for fsp in fsps]


def get_model_name(decay_mode):
    """
    Return the decay model name in a Tree of name 'decayline'.

    Parameters
    ----------
    decay_mode: Lark Tree instance
        Input Tree satisfying Tree.data=='decayline'.

    Examples
    --------
    For a decay
        Decay MyB_s0
            1.000     K+     K-     SSD_CP 20.e12 0.1 1.0 0.04 9.6 -0.8 8.4 -0.6;
        Enddecay
    the string 'SSD_CP' will be returned.
    """
    if not isinstance(decay_mode, Tree) or decay_mode.data != 'decayline':
        raise RuntimeError("Input not an instance of a 'decayline' Tree!")

    lm = list(decay_mode.find_data('model'))
    return lm[0].children[0].value


def get_model_parameters(decay_mode):
    """
    Return a list of decay model parameters in a Tree of name 'decayline',
    if defined, else an empty string.

    Parameters
    ----------
    decay_mode: Lark Tree instance
        Input Tree satisfying Tree.data=='decayline'.

    Examples
    --------
    For a decay
        Decay MyB_s0
            1.000     K+     K-     SSD_CP 20.e12 0.1 1.0 0.04 9.6 -0.8 8.4 -0.6;
        Enddecay
    the list
        [20000000000000.0, 0.1, 1.0, 0.04, 9.6, -0.8, 8.4, -0.6]
    will be returned.
    """
    if not isinstance(decay_mode, Tree) or decay_mode.data != 'decayline':
        raise RuntimeError("Input not an instance of a 'decayline' Tree!")

    lmo = list(decay_mode.find_data('model_options'))
    return [float(tree.children[0].value) for tree in lmo[0].children] if len(lmo) == 1 else ''


def get_decays(parsed_file):
    """
    Return a list of all decay definitions in the input parsed file,
    of the form
    "Decay <MOTHER>",
    as a tuple of Lark Tree instances with Tree.data=='decay', i.e.,
    [Tree(decay, [Tree(particle, [Token(LABEL, <MOTHER1>]), ...),
     Tree(decay, [Tree(particle, [Token(LABEL, <MOTHER2>]), ...)].

    Parameters
    ----------
    parsed_file: Lark Tree instance
        Input parsed file.
    """
    if not isinstance(parsed_file, Tree) :
        raise RuntimeError("Input not an instance of a Tree!")

    try:
        return list(parsed_file.find_data('decay'))
    except:
        RuntimeError("Input parsed file does not seem to have the expected structure.")


def get_charge_conjugate_decays(parsed_file):
    """
    Return a (sorted) list of all charge conjugate decay definitions
    in the input parsed file, of the form "CDecay <MOTHER>", as
    ['MOTHER1', 'MOTHER2', ...].

    Parameters
    ----------
    parsed_file: Lark Tree instance
        Input parsed file.
    """
    if not isinstance(parsed_file, Tree) :
        raise RuntimeError("Input not an instance of a Tree!")

    try:
        return sorted([tree.children[0].children[0].value for tree in parsed_file.find_data('cdecay')])
    except:
        RuntimeError("Input parsed file does not seem to have the expected structure.")


def get_definitions(parsed_file):
    """
    Return a dictionary of all definitions in the input parsed file, of the form
    "Define <NAME> <VALUE>", as {'NAME1': VALUE1, 'NAME2': VALUE2, ...}.

    Parameters
    ----------
    parsed_file: Lark Tree instance
        Input parsed file.
    """
    if not isinstance(parsed_file, Tree) :
        raise RuntimeError("Input not an instance of a Tree!")

    try:
        return {tree.children[0].children[0].value:float(tree.children[1].children[0].value)
            for tree in parsed_file.find_data('define')}
    except:
        RuntimeError("Input parsed file does not seem to have the expected structure.")


def get_aliases(parsed_file):
    """
    Return a dictionary of all aliases in the input parsed file, of the form
    "Alias <NAME> <ALIAS>", as {'NAME1': ALIAS1, 'NAME2': ALIAS2, ...}.

    Parameters
    ----------
    parsed_file: Lark Tree instance
        Input parsed file.
    """
    if not isinstance(parsed_file, Tree) :
        raise RuntimeError("Input not an instance of a Tree!")

    try:
        return {tree.children[0].children[0].value:tree.children[1].children[0].value
            for tree in parsed_file.find_data('alias')}
    except:
        RuntimeError("Input parsed file does not seem to have the expected structure.")


def get_charge_conjugate_defs(parsed_file):
    """
    Return a dictionary of all charge conjugate definitions
    in the input parsed file, of the form "ChargeConj <PARTICLE> <CC_PARTICLE>",
    as {'PARTICLE1': CC_PARTICLE1, 'PARTICLE2': CC_PARTICLE2, ...}.

    Parameters
    ----------
    parsed_file: Lark Tree instance
        Input parsed file.
    """
    if not isinstance(parsed_file, Tree) :
        raise RuntimeError("Input not an instance of a Tree!")

    try:
        return {tree.children[0].children[0].value:tree.children[1].children[0].value
            for tree in parsed_file.find_data('chargeconj')}
    except:
        RuntimeError("Input parsed file does not seem to have the expected structure.")


def get_pythia_definitions(parsed_file):
    """
    Return a dictionary of all Pythia definitions in the input parsed file,
    of the form
    "PythiaBothParam <NAME>=<LABEL>"
    or
    "PythiaBothParam <NAME>=<NUMBER>",
    as {'NAME1': 'LABEL1', 'NAME2': VALUE2, ...}.

    Parameters
    ----------
    parsed_file: Lark Tree instance
        Input parsed file.
    """
    if not isinstance(parsed_file, Tree) :
        raise RuntimeError("Input not an instance of a Tree!")

    def str_or_float(arg):
        try:
            return float(arg)
        except:
            return arg

    try:
        return {'{0}:{1}'.format(tree.children[0].value, tree.children[1].value):str_or_float(tree.children[2].value)
            for tree in parsed_file.find_data('pythia_def')}
    except:
        RuntimeError("Input parsed file does not seem to have the expected structure.")


def get_lineshape_definitions(parsed_file):
    """
    Return a dictionary of all SetLineshapePW definitions in the input parsed file,
    of the form
    "SetLineshapePW <MOTHER> <DAUGHTER1> <DAUGHTER2> <VALUE>",
    as
    [(['MOTHER1', 'DAUGHTER1-1', 'DAUGHTER1-2'], VALUE1),
     (['MOTHER2', 'DAUGHTER2-1', 'DAUGHTER2-2'], VALUE2),
     ...]

    Parameters
    ----------
    parsed_file: Lark Tree instance
        Input parsed file.
    """
    if not isinstance(parsed_file, Tree) :
        raise RuntimeError("Input not an instance of a Tree!")

    try:
        d = list()
        for tree in parsed_file.find_data('setlspw'):
            particles = [p.children[0].value for p in tree.children[:-1]]
            val = int(tree.children[3].children[0].value)
            d.append((particles, val))
        return d
    except:
        RuntimeError("Input parsed file does not seem to have the expected structure.")


def get_global_photos_flag(parsed_file):
    """
    Return a boolean-like PhotosEnum enum specifying whether or not PHOTOS
    has been enabled.

    Note: PHOTOS is turned on(off) for all decays with the global flag
    yesPhotos(noPhotos).

    Parameters
    ----------
    parsed_file: Lark Tree instance
        Input parsed file.

    Returns
    -------
    out: PhotosEnum, default=PhotosEnum.no
        PhotosEnum.yes / PhotosEnum.no if PHOTOS enabled / disabled
    """
    if not isinstance(parsed_file, Tree) :
        raise RuntimeError("Input not an instance of a Tree!")

    # Check if the flag is not set more than once, just in case ...
    tree = tuple(parsed_file.find_data('global_photos'))
    print('TREE:', tree)
    if len(tree) == 0:
        return PhotosEnum.no
    elif len(tree) > 1:
            warnings.warn("PHOTOS flag re-set! Using flag set in last ...")

    tree = tree[-1]

    try:
        val = tree.children[0].data
        return PhotosEnum.yes if val=='yes' else PhotosEnum.no
    except:
        RuntimeError("Input parsed file does not seem to have the expected structure.")


class TreeToDec(Transformer):
    def yes(self, items):
        return True
    def no(self, items):
        return False
    def global_photos(self, items):
        item, = items
        return PhotosEnum.yes if item else PhotosEnum.no
    def value(self, items):
        item, = items
        return float(item)
    def label(self, items):
        item, = items
        return str(item)
    def photos(self, items):
        return PhotosEnum.yes


def define(transformed):
    return {x.children[0]:x.children[1] for x in transformed.find_data('define')}
def pythia_def(transformed):
    return [x.children for x in transformed.find_data('pythia_def')]
def alias(transformed):
    return {x.children[0]:x.children[1] for x in transformed.find_data('alias')}

def chargeconj(transformed):
    return {x.children[0]:x.children[1] for x in transformed.find_data('chargeconj')}

# Commands
def global_photos(transformed):
    return {x.children[0]:x.children[1] for x in transformed.find_data('global_photos')}

def decay(transformed):
    return Tree('decay', list(transformed.find_data('decay')))
def cdecay(transformed):
    return [x.children[0] for x in transformed.find_data('cdecay')]
def setlspw(transformed):
    return list(transformed.find_data('setlspw'))