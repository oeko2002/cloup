"""
Example of options groups, "nested style" (recommended).

The decorator @option_group() is overloaded with two signatures.
Basically, you can specify the optional help string either:

1) as keyword argument, after the options
    @option_group(name: str,
                  *options: GroupedOption,
                  help: Optional[str] = None
                  constraint: Optional[Constraint] = None)

2) as 2nd positional argument, before the options

    @option_group(name: str,
                  help: str,
                  *options: GroupedOption,
                  constraint: Optional[Constraint] = None)
"""
from pprint import pprint

import click
from click import Choice

import cloup
from cloup import option, option_group
from cloup.constraints import If, SetAtLeast, check_constraint, mutually_exclusive


@cloup.command(name='cloup')
@click.argument('arg', required=False)
@option_group(
    'First group title',
    "This is a very long description of the option group. I don't think this is "
    "needed very often; still, if you want to provide it, you can pass it as 2nd "
    "positional argument or as keyword argument 'help' after all options.",
    option('--one', type=int, help='a 1st cool option'),
    option('--two', help='a 2nd cool option'),
    option('--three', help='a 3rd cool option'),
    constraint=SetAtLeast(1),
)
@option_group(
    'Second group name',
    option('--four', help='a 4th cool option'),
    option('--five', help='a 5th cool option'),
    option('--six', help='a 6th cool option'),
    constraint=If('three', then=SetAtLeast(1)),
)
@option('--seven', help='first uncategorized option', type=Choice('yes no ask'.split()))
@option('--eight', help='second uncategorized option')
def main(**kwargs):
    """ A CLI that does nothing. """

    # What if you want to define a constraint on a group of parameters that
    # don't form an OptionGroup? No problem, you can check a constraint on any
    # group of parameters by providing the *names* of the parameters in a list;
    # the needed Context is automatically grabbed using click.get_current_context().
    mutually_exclusive(['one', 'six'])

    pprint(kwargs, indent=3)


if __name__ == '__main__':
    main()
