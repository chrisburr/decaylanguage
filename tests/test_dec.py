import pytest

try:
    from pathlib2 import Path
except ImportError:
    from pathlib import Path

from lark import Tree, Token

from decaylanguage import data

from decaylanguage.dec.dec import DecFileParser
from decaylanguage.dec.dec import DecFileNotParsed, DecayNotFound
from decaylanguage.dec.dec import ChargeConjugateReplacement
from decaylanguage.dec.dec import get_decay_mother_name
from decaylanguage.dec.dec import get_final_state_particle_names

# New in Python 3
try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError


DIR = Path(__file__).parent.resolve()


def test_default_constructor():
    p = DecFileParser(DIR / 'data/test_example_Dst.dec')
    assert p is not None


def test_from_file():
    p = DecFileParser.from_file(DIR / 'data/test_example_Dst.dec')
    assert p is not None


def test_unknown_decfile():
    with pytest.raises(FileNotFoundError):
        p = DecFileParser.from_file('non-existent.dec')


def test_non_parsed_decfile():
    with pytest.raises(DecFileNotParsed):
        p = DecFileParser.from_file(DIR / 'data/test_example_Dst.dec')
        p.list_decay_mother_names()


def test_non_existent_decay():
    with pytest.raises(DecayNotFound):
        p = DecFileParser(DIR / 'data/test_example_Dst.dec')
        p.parse()
        p.list_decay_modes('XYZ')


def test_default_grammar_loading():
    p = DecFileParser.from_file(DIR / 'data/test_example_Dst.dec')
    assert p.grammar is not None


def test_explicit_grammar_loading():
    p = DecFileParser.from_file(DIR / 'data/test_example_Dst.dec')
    p.load_grammar(DIR / '../decaylanguage/data/decfile.lark')

    assert p.grammar_loaded is True


def test_string_representation():
        p = DecFileParser.from_file(DIR / 'data/test_example_Dst.dec')

        assert "n_decays" not in p.__str__()

        p.parse()
        assert "n_decays=5" in p.__str__()


def test_definitions_parsing():
    p = DecFileParser.from_file(DIR / 'data/defs-aliases-chargeconj.dec')
    p.parse()

    assert len(p.dict_definitions()) == 24


def test_aliases_parsing():
    p = DecFileParser.from_file(DIR / 'data/defs-aliases-chargeconj.dec')
    p.parse()

    assert len(p.dict_aliases()) == 132


def test_charge_conjugates_parsing():
    p = DecFileParser.from_file(DIR / 'data/defs-aliases-chargeconj.dec')
    p.parse()

    assert len(p.dict_charge_conjugates()) == 77


def test_pythia_definitions_parsing():
    p = DecFileParser.from_file(DIR / 'data/defs-aliases-chargeconj.dec')
    p.parse()

    assert p.dict_pythia_definitions() == {'ParticleDecays:mixB': 'off',
                                           'Init:showChangedSettings': 'off',
                                           'Init:showChangedParticleData': 'off',
                                           'Next:numberShowEvent': 0.0}


def test_list_lineshape_definitions():
    p = DecFileParser.from_file(DIR / 'data/defs-aliases-chargeconj.dec')
    p.parse()

    assert p.list_lineshape_definitions() == [(['D_1+', 'D*+', 'pi0'], 2),
                                              (['D_1+', 'D*0', 'pi+'], 2),
                                              (['D_1-', 'D*-', 'pi0'], 2),
                                              (['D_1-', 'anti-D*0', 'pi-'], 2),
                                              (['D_10', 'D*0', 'pi0'], 2),
                                              (['D_10', 'D*+', 'pi-'], 2),
                                              (['anti-D_10', 'anti-D*0', 'pi0'], 2),
                                              (['anti-D_10', 'D*-', 'pi+'], 2)]


def test_global_photos_flag():
    p = DecFileParser.from_file(DIR / 'data/defs-aliases-chargeconj.dec')
    p.parse()

    assert p.global_photos_flag() == True

def test_missing_global_photos_flag():
    p = DecFileParser.from_file(DIR / 'data/test_example_Dst.dec')
    p.parse()

    assert p.global_photos_flag() == False

def test_list_charge_conjugate_decays():
    p = DecFileParser.from_file(DIR / 'data/test_Bd2DmTauNu_Dm23PiPi0_Tau2MuNu.dec')
    p.parse()

    assert p.list_charge_conjugate_decays() == ['MyD+', 'MyTau+', 'Mya_1-', 'anti-B0sig']


def test_simple_dec():
    p = DecFileParser.from_file(DIR / 'data/test_example_Dst.dec')
    p.parse()

    assert p.list_decay_mother_names() == ['D*+', 'D*-', 'D0', 'D+', 'pi0']

    assert p.list_decay_modes('D0') == [['K-', 'pi+']]


def test_decay_mode_details():
    p = DecFileParser.from_file(DIR / 'data/test_example_Dst.dec')
    p.parse()

    tree_Dp = p._find_decay_modes('D+')[0]
    output = (1.0, ['K-', 'pi+', 'pi+', 'pi0'], 'PHSP', '')
    assert p._decay_mode_details(tree_Dp) == output


def test_duplicate_decay_definitions():
    p = DecFileParser(DIR / 'data/duplicate-decays.dec')
    p.parse()

    assert p.number_of_decays == 2

    assert p.list_decay_mother_names() == ['Sigma(1775)0', 'anti-Sigma(1775)0']


def test_build_decay_chain():
    p = DecFileParser.from_file(DIR / 'data/test_example_Dst.dec')
    p.parse()

    output = {'D+': [{'bf': 1.0, 'fs': ['K-', 'pi+', 'pi+', 'pi0'], 'm': 'PHSP', 'mp': ''}]}
    assert p.build_decay_chain('D+', stable_particles=['pi0']) == output


def test_Lark_ChargeConjugateReplacement_Visitor():
    """
    A simple example usage of the ChargeConjugateReplacement implementation
    of a Lark's Visitor, here replacing all particles in a 'decay' Tree
    by their antiparticles.
    """
    t = Tree('decay', [Tree('particle', [Token('LABEL', 'D0')]),
            Tree('decayline', [Tree('value', [Token('SIGNED_NUMBER', '1.0')]),
            Tree('particle', [Token('LABEL', 'K-')]),
            Tree('particle', [Token('LABEL', 'pi+')]),
            Tree('model', [Token('MODEL_NAME', 'PHSP')])])])

    ChargeConjugateReplacement().visit(t)

    assert get_decay_mother_name(t) == 'D~0'
    assert get_final_state_particle_names(t.children[1]) == ['K+', 'pi-']


def test_Lark_ChargeConjugateReplacement_Visitor_with_aliases():
    """
    Example with a D0 decay specified via an alias (MyD0).
    As such, it is necessary to state what the particle-antiparticle match is,
    which in decay files would mean the following lines:
       Alias       MyD0        D0
       Alias       MyAnti-D0   anti-D0
       ChargeConj  MyD0        MyAnti-D0
    A dictionary of matches should be passed to the Lark Visitor instance.
    """
    t = Tree('decay', [Tree('particle', [Token('LABEL', 'MyD0')]),
            Tree('decayline', [Tree('value', [Token('SIGNED_NUMBER', '1.0')]),
            Tree('particle', [Token('LABEL', 'K-')]),
            Tree('particle', [Token('LABEL', 'pi+')]),
            Tree('model', [Token('MODEL_NAME', 'PHSP')])])])

    dict_ChargeConj_defs = {'MyD0': 'MyAnti-D0'}

    ChargeConjugateReplacement(charge_conj_defs=dict_ChargeConj_defs).visit(t)

    assert get_decay_mother_name(t) == 'MyAnti-D0'
    assert get_final_state_particle_names(t.children[1]) == ['K+', 'pi-']


def test_creation_charge_conjugate_decays_in_decfile_with_aliases():
    """
    Decay file contains 5 particle decays defined via a 'Decay' statement
    and the 5 charge-conjugate decays defined via a 'CDecay' statement.
    The decay modes for the latter 5 should be created on the fly,
    hence providing in total 10 sets of particle decays parsed.
    """
    p = DecFileParser.from_file(DIR / 'data/test_Bd2DstDst.dec')
    p.parse()

    assert p.number_of_decays == 10


def test_creation_charge_conjugate_decays_in_decfile_without_CDecay_defs():
    """
    Decay file contains 5 particle decays defined via a 'Decay' statement,
    but no related charge-conjugate (CC) decays defined via a 'CDecay' statement
    since the CC particle decays are also defined via a 'Decay' statement
    for all cases except self-conjugate (mother) particles, obviously ;-).
    This being said, this decay file is in fact incomplete by itself,
    as there are no instructions on how to decay the anti-D0 and the D-!
    In short, there should only be 5 sets of decay modes parsed.
    """
    p = DecFileParser.from_file(DIR / 'data/test_example_Dst.dec')
    p.parse()

    assert p.number_of_decays == 5