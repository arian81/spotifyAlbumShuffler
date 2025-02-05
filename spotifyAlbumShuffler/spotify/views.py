import uuid

import spotipy
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect

# Create your views here.
from django.template import loader
from rest_framework.exceptions import PermissionDenied
from spotipy import SpotifyOAuth
from rest_framework import viewsets, permissions

from spotifyAlbumShuffler.spotify import logic, tasks
from spotifyAlbumShuffler.spotify.models import SpotifyPlaylist, SpotifyUser
from spotifyAlbumShuffler.spotify.serializers import SpotifyPlaylistSerializer

from authlib.integrations.django_client import OAuth

from spotifyAlbumShuffler.spotify.tasks import playlists_for_user

oauth = OAuth()
oauth.register("spotify")


class SpotifyPlaylistViewSet(viewsets.ModelViewSet):
    serializer_class = SpotifyPlaylistSerializer
    queryset = SpotifyPlaylist.objects.all()
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        try:
            user_id = self.request.session['user_id']
        except KeyError:
            raise PermissionDenied(detail="User not authenticated")
        return SpotifyPlaylist.objects.filter(owner__spotify_user_id=user_id)


def status(request):
    try:
        user_id = request.session['user_id']
    except KeyError:
        user_id = ""
    logged_in = bool(user_id)
    if logged_in:
        display_name = SpotifyUser.objects.get(spotify_user_id=request.session['user_id']).display_name
    else:
        display_name = ""
    return JsonResponse({
        "logged_in": logged_in,
        "user_id": user_id,
        "display_name": display_name
    })


def login(request):
    if 'user_id' in request.session:
        return redirect("http://localhost")
    spotify_auth = oauth.spotify
    redirect_uri = "http://localhost/callback/"
    return spotify_auth.authorize_redirect(request, redirect_uri)


def authorize(request):
    token = oauth.spotify.authorize_access_token(request)
    resp = oauth.spotify.get('me', token=token)
    resp.raise_for_status()
    print(resp.json())
    data = resp.json()
    user, created = SpotifyUser.objects.get_or_create(
        spotify_user_id=data['id']
    )
    if created:
        user.token = token
        user.display_name = data['display_name']
    user.save()
    request.session['user_id'] = data['id']
    playlists_for_user(user.spotify_user_id)
    tasks.batch_refresh_image(user.spotify_user_id)
    return redirect("http://localhost")


def refresh_playlists(request):
    try:
        user_id = request.session['user_id']
    except KeyError:
        raise PermissionDenied(detail="User not authenticated")
    playlists_for_user(user_id)
    return HttpResponse(status=204)


def album_render(request):
    scopes = ["playlist-modify-private", "playlist-read-private", "playlist-modify-public"]
    client = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            scope=scopes,
            open_browser=False,
            show_dialog=True,
        )
    )

    logic.refresh_user_playlists(client)
    playlists_list = SpotifyPlaylist.objects.all()
    template = loader.get_template('album_render.html')
    context = {
        'playlists': playlists_list,
    }
    return HttpResponse(template.render(context, request))


def album_shuffle(request):
    playlists_list = SpotifyPlaylist.objects.filter(back_to_back=True).all()
    for playlist in playlists_list:
        logic.shuffle_playlist(client, playlist)
    return HttpResponse("Shuffled playlists")
