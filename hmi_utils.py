def shrink_message_type(message_type):
    first_two_words = message_type.split()[:2]
    shrinked_message_type = ' '.join(first_two_words).replace(' ', '_').lower()
    return shrinked_message_type
