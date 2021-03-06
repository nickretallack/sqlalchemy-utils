"""
SQLAlchemy-Utils provides wide variety of range data types. All range data types return
Interval objects of intervals_ package. In order to use range data types you need to install intervals_ with:

::

    pip install intervals


Intervals package provides good chunk of additional interval operators that for example psycopg2 range objects do not support.



Some good reading for practical interval implementations:

http://wiki.postgresql.org/images/f/f0/Range-types.pdf


Range type operators
--------------------

SQLAlchemy-Utils supports many range type operators. These operators follow the `intervals` package interval coercion rules.

So for example when we make a query such as:

::

    session.query(Car).filter(Car.price_range == 300)


It is essentially the same as:

::

    session.query(Car).filter(Car.price_range == DecimalInterval([300, 300]))


Comparison operators
^^^^^^^^^^^^^^^^^^^^

All range types support all comparison operators (>, >=, ==, !=, <=, <).

::

    Car.price_range < [12, 300]

    Car.price_range == [12, 300]

    Car.price_range < 300

    Car.price_range > (300, 500)


Membership operators
^^^^^^^^^^^^^^^^^^^^

::

    Car.price_range.contains([300, 500])

    Car.price_range.contained_by([300, 500])

    Car.price_range.in_([[300, 500], [800, 900]])

    ~ Car.price_range.in_([[300, 400], [700, 800]])


.. _intervals: https://github.com/kvesteri/intervals
"""
from collections import Iterable
intervals = None
try:
    import intervals
except ImportError:
    pass
import six
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import (
    INT4RANGE,
    DATERANGE,
    NUMRANGE,
    TSRANGE,
)
from sqlalchemy import types
from ..exceptions import ImproperlyConfigured
from .scalar_coercible import ScalarCoercible


class RangeComparator(types.TypeEngine.Comparator):
    @classmethod
    def coerced_func(cls, func):
        def operation(self, other, **kwargs):
            other = self.coerce_arg(other)
            return getattr(types.TypeEngine.Comparator, func)(
                self, other, **kwargs
            )
        return operation

    def coerce_arg(self, other):
        coerced_types = (
            self.type.interval_class.type,
            tuple,
            list,
        ) + six.string_types

        if isinstance(other, coerced_types):
            return self.type.interval_class(other)
        return other

    def in_(self, other):
        if (
            isinstance(other, Iterable) and
            not isinstance(other, six.string_types)
        ):
            other = map(self.coerce_arg, other)
        return super(RangeComparator, self).in_(other)

    def notin_(self, other):
        if (
            isinstance(other, Iterable) and
            not isinstance(other, six.string_types)
        ):
            other = map(self.coerce_arg, other)
        return super(RangeComparator, self).notin_(other)

    def __rshift__(self, other, **kwargs):
        """
        Returns whether or not given interval is strictly right of another
        interval.

        [a, b] >> [c, d]        True, if a > d
        """
        other = self.coerce_arg(other)
        return self.op('>>')(other)

    def __lshift__(self, other, **kwargs):
        """
        Returns whether or not given interval is strictly left of another
        interval.

        [a, b] << [c, d]        True, if b < c
        """
        other = self.coerce_arg(other)
        return self.op('<<')(other)

    def contains(self, other, **kwargs):
        other = self.coerce_arg(other)
        return self.op('@>')(other)

    def contained_by(self, other, **kwargs):
        other = self.coerce_arg(other)
        return self.op('<@')(other)


funcs = [
    '__eq__',
    '__ne__',
    '__lt__',
    '__le__',
    '__gt__',
    '__ge__',
]


for func in funcs:
    setattr(
        RangeComparator,
        func,
        RangeComparator.coerced_func(func)
    )


class RangeType(types.TypeDecorator, ScalarCoercible):
    comparator_factory = RangeComparator

    def __init__(self, *args, **kwargs):
        if intervals is None:
            raise ImproperlyConfigured(
                'RangeType needs intervals package installed.'
            )
        super(RangeType, self).__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            # Use the native JSON type.
            return dialect.type_descriptor(self.impl)
        else:
            return dialect.type_descriptor(sa.String(255))

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value:
            return self.canonicalize_result_value(
                self.interval_class(value)
            )
        return value

    def canonicalize_result_value(self, value):
        return intervals.canonicalize(value, True, True)

    def _coerce(self, value):
        if value is not None:
            value = self.interval_class(value)
        return value


class IntRangeType(RangeType):
    """
    IntRangeType provides way for saving ranges of integers into database. On
    PostgreSQL this type maps to native INT4RANGE type while on other drivers
    this maps to simple string column.

    Example::


        from sqlalchemy_utils import IntRangeType


        class Event(Base):
            __tablename__ = 'user'
            id = sa.Column(sa.Integer, autoincrement=True)
            name = sa.Column(sa.Unicode(255))
            estimated_number_of_persons = sa.Column(IntRangeType)


        party = Event(name=u'party')

        # we estimate the party to contain minium of 10 persons and at max
        # 100 persons
        party.estimated_number_of_persons = [10, 100]

        print party.estimated_number_of_persons
        # '10-100'


    IntRangeType returns the values as IntInterval objects. These objects
    support many arithmetic operators::


        meeting = Event(name=u'meeting')

        meeting.estimated_number_of_persons = [20, 40]

        total = (
            meeting.estimated_number_of_persons +
            party.estimated_number_of_persons
        )
        print total
        # '30-140'
    """
    impl = INT4RANGE

    def __init__(self, *args, **kwargs):
        super(IntRangeType, self).__init__(*args, **kwargs)
        self.interval_class = intervals.IntInterval



class DateRangeType(RangeType):
    """
    DateRangeType provides way for saving ranges of dates into database. On
    PostgreSQL this type maps to native DATERANGE type while on other drivers
    this maps to simple string column.

    Example::


        from sqlalchemy_utils import DateRangeType


        class Reservation(Base):
            __tablename__ = 'user'
            id = sa.Column(sa.Integer, autoincrement=True)
            room_id = sa.Column(sa.Integer))
            during = sa.Column(DateRangeType)
    """
    impl = DATERANGE

    def __init__(self, *args, **kwargs):
        super(DateRangeType, self).__init__(*args, **kwargs)
        self.interval_class = intervals.DateInterval


class NumericRangeType(RangeType):
    impl = NUMRANGE

    def __init__(self, *args, **kwargs):
        super(DateRangeType, self).__init__(*args, **kwargs)
        self.interval_class = intervals.DecimalInterval


class DateTimeRangeType(RangeType):
    impl = TSRANGE

    def __init__(self, *args, **kwargs):
        super(DateRangeType, self).__init__(*args, **kwargs)
        self.interval_class = intervals.DateTimeInterval
