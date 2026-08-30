import math

def split_list_into_chunks(lst, chunk_size):
    """
    Split a list into chunks of a given size.

    Parameters:
    lst (list): The list to be split.
    chunk_size (int): The size of each chunk.

    Returns:
    list: A list of chunks.

    >>> split_list_into_chunks([1, 2, 3, 4, 5], 2)
    [[1, 2], [3, 4], [5]]
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def pages_needed(num_items, page_size):
    """
    Calculate the number of pages needed for a given number of items and page size.

    Parameters:
    num_items (int): The total number of items.
    page_size (int): The number of items per page.

    Returns:
    int: The number of pages required.

    >>> pages_needed(10, 3)
    4
    """
    return math.ceil(num_items / page_size)

def truncate_string(text, max_length):
    """
    Truncate a string to a specified maximum length and add an ellipsis if necessary.

    Parameters:
    text (str): The string to be truncated.
    max_length (int): The maximum length of the string after truncation.

    Returns:
    str: The truncated string with an ellipsis if necessary.

    >>> truncate_string("Hello, World!", 5)
    'He...'
    """
    return text[:max_length] + "..." if len(text) > max_length else text

def format_byte_count(byte_count):
    """
    Format a byte count as kilobytes (KB) or megabytes (MB).

    Parameters:
    byte_count (int): The number of bytes to be formatted.

    Returns:
    str: A string representation of the byte count in KB or MB.

    >>> format_byte_count(1024)
    '1.0 KB'
    >>> format_byte_count(1536)
    '1.5 KB'
    """
    kb = byte_count / 1024
    mb = kb / 1024
    if kb < 1:
        return f"{kb:.1f} KB"
    elif mb < 1:
        return f"{mb:.1f} MB"
    else:
        return f"{kb:.1f} MB"

# Test the functions using the provided doctests
if __name__ == "__main__":
    import doctest
    doctest.testmod()
