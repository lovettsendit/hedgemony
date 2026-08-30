def mean(lst):
    """
    Calculate the mean (average) of numbers in the list.

    >>> mean([1, 2, 3, 4])
    2.5
    """
    return sum(lst) / len(lst)

def median(lst):
    """
    Calculate the median of numbers in the list.

    >>> median([1, 3, 2, 4, 5])
    3
    """
    sorted_lst = sorted(lst)
    n = len(sorted_lst)
    mid = n // 2

    if n % 2 == 0:
        return (sorted_lst[mid - 1] + sorted_lst[mid]) / 2.0
    else:
        return sorted_lst[mid]

def percentage_change(before, after):
    """
    Calculate the percentage change between before and after values.

    >>> percentage_change(100, 150)
    50.0
    """
    return ((after - before) / before) * 100

def round_up_to_nearest_multiple(number, n):
    """
    Round up the number to the nearest multiple of n.

    >>> round_up_to_nearest_multiple(7, 3)
    9
    """
    return (number + (n - 1)) // n * n
