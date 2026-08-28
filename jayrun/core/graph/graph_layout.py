from ..operator.base import BaseOperator


class GraphLayout:
    def __init__(self, num_rows: int) -> None:
        if type(num_rows) is not int:
            raise TypeError("num_rows must be an integer")

        if num_rows <= 0:
            raise ValueError("num_rows must be greater than zero")

        self.num_rows = num_rows
        self._rows: list[list[BaseOperator | None]] = [[] for _ in range(num_rows)]

    def append(
        self, column: tuple[BaseOperator | None, ...] | list[BaseOperator | None]
    ) -> None:
        if len(column) != len(self._rows):
            raise IndexError(
                f"the matrix has {len(self._rows)} rows, the column length is {len(column)}"
            )
        for operator, row in zip(column, self._rows):
            row.append(operator)

    def row(self, number: int) -> tuple[BaseOperator | None, ...]:
        if not isinstance(number, int):
            raise TypeError("the row number must be an integer")
        if number < 0:
            raise IndexError("the row number must be a positive number")
        if number > len(self._rows) - 1:
            raise IndexError(f"the matrix has {len(self._rows)} rows, exceed")
        return tuple(self._rows[number])

    def col(self, number: int) -> tuple[BaseOperator | None, ...]:
        if not isinstance(number, int):
            raise TypeError("the column number must be an integer")
        if number < 0:
            raise IndexError("the column number must be a positive number")
        if number > len(self._rows[0]) - 1:
            raise IndexError(f"the matrix has {len(self._rows[0])} columns, exceed")
        return tuple(row[number] for row in self.rows)

    @property
    def row_counts(self) -> tuple[int, ...]:
        boolean = [[bool(x) for x in row] for row in self._rows]
        return tuple(sum(x) for x in boolean)

    @property
    def rows(self) -> tuple[tuple[BaseOperator | None, ...], ...]:
        return tuple(tuple(row) for row in self._rows)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.num_rows, len(self._rows[0]))
