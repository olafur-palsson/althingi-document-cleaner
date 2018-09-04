import re

from lxml.builder import E

from utils import order_among_siblings
from utils import super_iter

def regexify_markers(text):
    '''
    Replaces markers in given text with regex that will match those same
    markers. The point is to have a regex that will match the string both with
    and without markers.
    '''

    text = re.sub(
        r'\[ ?',
        r'(\[? ?)?',
        text
    )
    text = re.sub(
        r'\],? <sup style="font-size:60%"> ?\d+\) ?</sup>,? ?',
        r'(\],? <sup( style="font-size:60%")?> ?\d+\) ?</sup>)?,? ?',
        text
    )
    text = re.sub(
        r'… <sup style="font-size:60%"> \d+\) </sup>,? ?',
        r'(… <sup( style="font-size:60%")?> \d+\) </sup>)?,? ?',
        text
    )
    text = text.replace(' ,', r' ?,')

    return text


def strip_markers(text):
    '''
    Strips markers from text and cleans up resulting weirdness.
    '''

    text = text.replace('…', '')
    text = text.replace('[', '')
    text = text.replace(']', '')
    text = re.sub(r'<sup style="font-size:60%"> \d+\) </sup>', '', text)

    while text.find('  ') > -1:
        text = text.replace('  ', ' ')

    text = text.replace(' ,', ',')

    return text


def next_footnote_sup(elem, cursor):
    '''
    Returns the next footnote number in the given element. Sometimes the
    number is located in the next element, for example: "or not the
    [minister]. <sup ...> 2) </sup>". In these cases we'll need to peek into
    the next element. We'll do this by changing the haystack in which we look.
    We won't use the cursor when looking for it though, because it will
    definitely be the first <sup> we run into, inside the next element.

    By the way:
        len('<sup style="font-size:60%">') == 27
    '''
    if elem.text.find('<sup style="font-size:60%">', cursor) > -1:
        haystack = elem.text
        num_start = haystack.find('<sup style="font-size:60%">', cursor) + 27
        num_end = haystack.find('</sup>', cursor)
        num_text = haystack[num_start:num_end]
        num = num_text.strip().strip(')')
    else:
        haystack = elem.getnext().text
        num_start = haystack.find('<sup style="font-size:60%">') + 27
        num_end = haystack.find('</sup>')
        num_text = haystack[num_start:num_end]
        num = num_text.strip().strip(')')

    return num


def generate_ancestors(elem, parent):
    # Locations of markers in footnote XML are denoted as a list of tags,
    # whose name correspond to the tag name where the marker is to be located,
    # and  whose value represents the target node's "nr" attribute.
    # Example:
    #
    # <art nr="5">
    #   <subart nr="1">
    #     <sen>[Notice the markers?]</sen>
    #   </subart>
    # </art>
    #
    # This will result in location XML in the footnote XML as such:
    #
    # <location>
    #   <art>5</art>
    #   <subart>1</subart>
    #   <sen>1</sen>
    # </location>
    #
    # To achieve this, we iterate through the ancestors of the node currently
    # being processed. For each ancestor that we find, we add to the location
    # XML.
    ancestors = []
    for ancestor in elem.iterancestors():
        ancestors.insert(0, E(ancestor.tag, ancestor.attrib['nr']))
        if ancestor == parent:
            # We're not interested in anything
            # beyond the parent node.
            break

    # If we cannot find a 'nr' attribute, we'll figure it out and still put it in.
    if 'nr' in elem.attrib:
        ancestors.append(E(elem.tag))
    else:
        ancestors.append(E(elem.tag, str(order_among_siblings(elem))))

    return ancestors

# A function for intelligently splitting textual content into separate
# sentences based on linguistic rules and patterns.
def separate_sentences(content):

    # Contains the resulting list of sentences.
    sens = []

    # Reference shorthands are strings that are used in references. They are
    # often combined to designate a particular location in legal text, for
    # example "7. tölul. 2. mgr. 5. gr.", meaning numerical article 7 in
    # subarticle 2 of article 5. Their use results in various combinations of
    # numbers and dots that need to be taken into account to avoid wrongly
    # starting a new sentence when they are encountered.
    reference_shorthands = ['gr', 'mgr', 'málsl', 'tölul', 'staf']

    # Encode recognized short-hands in text so that the dots in them don't get
    # confused for an end of a sentence. They will be decoded when appended to
    # the resulting list.
    #
    # Note that whether there should be a dot at the end of these depends on
    # how they are typically used in text. Any of these that might be used at
    # the end of a sentence should preferably not have a dot at the end. Those
    # that are very unlikely to be used at the end of a sentence should
    # however and with a dot.
    #
    # This is because there is an ambiguity after one of these is used, if the
    # following letter is a capital letter, because the capital letter may
    # indicate either the start of a new sentence, OR it could just be the
    # name of something, since names start with capital letters. This is why
    # "a.m.k." and "þ.m.t." end with dots, because they very well have a
    # capitalized name after them but are very unlikely to be used at the end
    # of a sentence, while "o.fl." is extremely unlikely to be followed by a
    # name, but may very well end a sentence.
    recognized_shorts = [
        't.d.',
        'þ.m.t.',
        'sbr.',
        'nr.',
        'skv.',
        'm.a.',
        'a.m.k.',
        'þ.e.',
        'o.fl',
    ]
    for r in recognized_shorts:
        content = content.replace(r, r.replace('.', '[DOT]'))

    # HTML tables should never be split up into separate sentences, so we'll
    # encode every dot in them.
    cursor = 0
    html_loc = content.find('<table width="100%">', cursor)
    while html_loc > -1:
        html_end_loc = content.find('</table>', cursor) + len('</table>')

        # Fish out the HTML table.
        table_content = content[html_loc:html_end_loc]

        # Encode the dots in the HTML table.
        table_content = table_content.replace('.', '[DOT]')

        # Stitch the encoded table back into the content.
        content = content[:html_loc] + table_content + content[html_end_loc:]

        # Continue to see if we find more tables.
        cursor = html_loc + 1
        html_loc = content.find('<table width="100%">', cursor)
    del cursor
    del html_loc

    # The collected sentence so far. Chunks are appended to this string until
    # a new sentence is determined to be appropriate. Starts empty and and is
    # reset for every new sentence.
    collected = ''

    # We'll default to splitting chunks by dots. As we iterate through the
    # chunks, we will determine the cases where we actually don't want to
    # start a new sentence.
    chunks = super_iter(content.split('.'))

    for chunk in chunks:
        # There is usually a period at the end and therefore a trailing, empty
        # chunk that we're not interested in.
        if chunk == '':
            continue

        # Start a new sentence by default. We'll only continue to gather the
        # chunks into the collected sentence when we find a reason to, but
        # normally a dot means an end of a sentence, thus a new one.
        split = True

        # Collect the chunk into the sentence so far. If we decide not to
        # start a new sentence, then this variable will grow until we decide
        # to, at which point it's added to the result and cleared.
        collected += chunk

        # Previews the next chunk before it is processed itself, so that we
        # can determine the context in both directions.
        next_chunk = chunks.peek()

        if next_chunk is not None:
            # We need to strip markers from the next chunk, because various
            # symbols may get in the way of us accurately figuring out how the
            # next chunk starts.
            next_chunk = strip_markers(next_chunk)

            # Don't start a new sentence if the first character in the next
            # chunk is lowercase.
            if len(next_chunk) > 1 and next_chunk[0] == ' ' and next_chunk[1].islower():
                split = False

            # Don't start a new sentence if the character immediately
            # following the dot is a symbol indicating that the sentence's end
            # has not yet been reached (comma, semicomma etc.).
            if len(next_chunk) > 0 and next_chunk[0] in [',', ';', '–', '-', '[', ']', '…']:
                split = False

            # Don't start a new sentence if the dot is a part of a number.
            if len(next_chunk) > 0 and next_chunk[0].isdigit():
                split = False

            # Don't split if dealing with a reference to an article,
            # sub-article, numerical article or whatever.
            # Example:
            #    3. mgr. 4. tölul. 1. gr.
            last_word = chunk[chunk.rfind(' ')+1:]
            if last_word in reference_shorthands:
                next_chunk2 = chunks.peek(2)
                if next_chunk.strip().isdigit() and next_chunk2.strip() in reference_shorthands:
                    split = False

        # Add the dot that we dropped when splitting.
        collected += '.'

        if split:
            # Decode the "[DOT]"s back into normal dots.
            collected = collected.replace('[DOT]', '.')

            # Append the collected sentence.
            sens.append(collected.strip())

            # Reset the collected sentence.
            collected = ''

    # Since we needed to drop the dot when splitting, we needed to add it
    # again to every chunk. Sometimes the content in its entirety doesn't end
    # with a dot though, but rather a comma or colon or some such symbol. In
    # these cases we have wrongly added it to the final chunk after the split,
    # and so we'll just remove it here. This could probably be done somewhere
    # inside the loop, but it would probably just be less readable.
    if content and content[-1] != '.' and sens[-1][-1] == '.':
        sens[-1] = sens[-1].strip('.')

    return sens
