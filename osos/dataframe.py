from .column import (
    AbstractColOrLit, 
    Node,
    AbstractCol, 
    AbstractLit, 
    ArbitraryFunction, 
    SimpleContainer,
    FuncWithNoArgs,
)

import itertools
from copy import deepcopy, copy
import numpy as np
from typing import Iterable, Union
import pandas as pd


from .column import make_series_from_literal, NameString,ForwardRef,Func,FuncOrOp
from ._implementations import SeriesType
from .utils import flatten_cols
from .window import WindowSpec, ConcreteWindowSpec, EmptyWindow
from . import window


class DataFrame:

    @staticmethod
    def fromPandas(df) -> "DataFrame":
        return DataFrame(df)

    def __init__(self, data=None):
        self._data = pd.DataFrame(data)
    

    @staticmethod
    def fromDict(d) -> "DataFrame":
        return DataFrame(d)

    def toPandas(self) -> pd.DataFrame:
        return self._data

    def __str__(self):
        return self._data.to_string(index=False)

    __repr__ = __str__

    
    def _eval_recursive(self, expr: Union[Node, ForwardRef]) -> SeriesType:
        """
        Takes in an expression tree and recursively evaluates it. The recursive case is
        if the node is a function or operator that applies to one or more Series. 
        The base case is anything that doesn't have more nodes in its list of `args`.
        There are two broad base cases: a column type (or literal that becomes a column),
        and a `SimpleContainer` type that is just a name wrapped in a node.
        """
        no_op = Node(lambda x: x, (expr,))
        for node in no_op._args:
            if isinstance(node, ForwardRef):
                node = getattr(window, node.reference)(node.args)
            if isinstance(node, (AbstractColOrLit, SimpleContainer, EmptyWindow,FuncWithNoArgs)) :
                res = self._resolve_leaf(node)
            else:
                # a window is a node whose head is a function that returns a lightweight
                # class whose attributes are partition, order, rows between, and range between.
                # a window's `_args` are the unresolved version of those attributes
                if isinstance(node,FuncOrOp):
                    res = node._name(*list(self._eval_recursive(n) for n in node._args),
                    _over = self._eval_recursive(node._over))
                else:
                    res = node._name(*list(self._eval_recursive(n) for n in node._args))
            
                    
        return res


    def withColumn(self, name: str, expr: Node) -> "DataFrame":
        
        col = self._eval_recursive(expr)
        kwargs = {name:col}
        df = self._data.assign(**kwargs)
        return df

    def withColumnRenamed(self, oldname: str, newname: str) -> "DataFrame":
        df = DataFrame.fromPandas(self._data.rename({oldname:newname}, axis="columns"))
        return df

    def select(self, *exprs: Node) -> "DataFrame":
        flat_exprs = flatten_cols(exprs)
            
        cols = []
        for expr in flat_exprs:
            if isinstance(expr, str):
                expr = AbstractCol(expr)

            cols.append(self._eval_recursive(expr))
        newdf = DataFrame(pd.concat(cols, axis=1))
        return newdf

    def filter(self, *exprs: Node) -> "DataFrame":
        flat_exprs = flatten_cols(exprs)
        newdf = DataFrame(pd.DataFrame(self._data))
            
        for expr in flat_exprs:
            if isinstance(expr, str):
                expr = AbstractCol(expr)
            boolean_mask: pd.Series = self._eval_recursive(expr)
            assert boolean_mask.dtype == np.bool8, "`filter` expressions must return boolean results"
            newdf = newdf._data.iloc[boolean_mask]

        return newdf


    def groupBy(self, *exprs: Node) -> "GroupedData":
        flat_exprs = flatten_cols(exprs)
            
        cols = []
        for expr in flat_exprs:
            if isinstance(expr, str):
                expr = AbstractCol(expr)
            assert isinstance(expr, AbstractCol)
            cols.append(self._eval_recursive(expr))
        df = self
        return GroupedData(df._data.groupby(cols))

    def agg(self, *exprs: Node) -> "DataFrame":

        exprs = flatten_cols(exprs)
        out = []
        for expr in exprs:
            if hasattr(expr, "_over"):
                assert isinstance(expr._over, EmptyWindow), "Cannot use window functions in aggregate method"
            out.append(pd.Series(self._eval_recursive(expr)))
        

        newdf = DataFrame(pd.concat(out, axis=1).reset_index())

        return newdf

    def union(self, other: "DataFrame") -> "DataFrame":
        return DataFrame(pd.concat([self._data, other._data]).reindex())

    def unionAll(self, other: "DataFrame") -> "DataFrame":
        return self.union(other).dropDuplicates()

    def dropDuplicates(self, subset: list[str]) -> "DataFrame":
        return DataFrame(self._data.drop_duplicates(subset, ignore_index=True).reindex())

    def unionByName(self, other: "DataFrame") -> "DataFrame":
        assert set(self._data.columns) == set(other._data.columns)
        selfsort = self._data.sort_index(axis=1)
        othersort = other._data.sort_index(axis=1)
        return DataFrame(pd.concat([selfsort, othersort]))


    def join(self, other: "DataFrame", by: Union[str,list], how: str):
        by = [by] if isinstance(by, str) else by

        assert how in (
            'inner', 
            'cross', 
            'outer', 
            'full', 
            'fullouter', 
            'full_outer', 
            'left', 
            'leftouter', 
            'left_outer', 
            'right', 
            'rightouter', 
            'right_outer', 
            'semi', 
            'leftsemi', 
            'left_semi', 
            'anti', 
            'leftanti', 
            'left_anti',
        )
        if 'anti' in how:
            how = 'anti'
        elif 'semi' in how:
            how = 'semi'
        elif 'left' in how:
            how = 'left'
        elif 'right' in how:
            how = 'right'
        elif 'outer' in how:
            how = 'outer'

        out = pd.merge(self._data, other._data, how=how, on=by)
        # we have to be careful here as pandas will include records where
        # join columns are NaN in both the left and right datasets.
        # This will happen if *any* of the join columns are null
        bad_records = out[by].isnull().any(axis=1)
        return DataFrame(out[~bad_records].reindex())


         
    def _resolve_leaf(self, node: Node) -> Node:
        if isinstance(node, AbstractCol):
            return self._data[node._name]
        elif isinstance(node, AbstractLit):
            return make_series_from_literal(scalar_data=node._name, length=len(self._data.index))
        elif isinstance(node, SimpleContainer):
            return node._name
        else:
            return node

    
class GroupedData(DataFrame):
    def __init__(self, data=None, cols=None):
        self._data = data if data is not None else pd.DataFrame().groupby([])


    @property
    def groups(self):
        return pd.Series(self._data.groups.keys())

